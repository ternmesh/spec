#!/usr/bin/env python3
"""Generates and checks the companion protocol's test vectors (draft/companion.md).

    python3 vectors/tools/companion.py generate   # rewrite vectors/companion.json
    python3 vectors/tools/companion.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Before computing anything it checks its CRC against
the published check value for CRC-16/IBM-3740, and its encoder against frames worked by hand.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "companion.json"

VERSION = 1
MAX_FRAME = 180
MAGIC = b"\xf5\x54"
STREAM_HEAD = 4  # magic and length
STREAM_TAIL = 2  # the CRC

NAME_MAX, TEXT_MAX, FIRMWARE_MAX, REGION_MAX = 31, 128, 31, 15

# Each field is (name, kind, and for a string its longest). Kinds: u8, i8, u16, u32, addr (32
# bytes), str (a u8 length, then that many bytes of UTF-8).
U8, I8, U16, U32, ADDR, STR = "u8", "i8", "u16", "u32", "addr", "str"

FRAMES = {
    # Requests, client to node.
    0x01: ("HELLO", [("version", U8)]),
    0x02: ("SYNC", [("after", U32)]),
    0x03: ("PING", []),
    0x04: ("SET_TIME", [("time", U32)]),
    0x05: ("SET", [("setting", U8)]),  # then the setting's value, below
    0x10: ("SEND", [("ref", U32), ("to", ADDR), ("text", STR, TEXT_MAX)]),
    0x11: ("READ", [("through", U32)]),
    0x18: ("SAVE_CONTACT", [("address", ADDR), ("name", STR, NAME_MAX)]),
    0x19: ("REMOVE_CONTACT", [("address", ADDR)]),
    0x1A: ("END_SESSION", [("address", ADDR)]),
    # Answers, node to client.
    0x40: ("OK", []),
    0x41: ("ERROR", [("code", U8)]),
    0x42: ("INFO", [("version", U8), ("firmware", STR, FIRMWARE_MAX)]),
    0x43: ("SYNCED", []),
    0x44: ("QUEUED", [("id", U32)]),
    # News, node to client.
    0x80: ("SELF", [("address", ADDR), ("role", U8), ("region", STR, REGION_MAX), ("power", I8),
                    ("time", U32)]),
    0x81: ("CONTACT", [("address", ADDR), ("session", U8), ("name", STR, NAME_MAX)]),
    0x82: ("CONTACT_GONE", [("address", ADDR)]),
    0x83: ("MESSAGE", [("id", U32), ("contact", ADDR), ("time", U32), ("flags", U8),
                       ("state", U8), ("reason", U8), ("wait", U16), ("text", STR, TEXT_MAX)]),
    0x84: ("STATE", [("id", U32), ("state", U8), ("reason", U8), ("wait", U16)]),
    0x85: ("NEIGHBOUR", [("routing_id", U32), ("role", U8), ("snr_quarter_db", I8),
                         ("heard", U16)]),
    0x86: ("NEIGHBOUR_GONE", [("routing_id", U32)]),
    0x87: ("AIRTIME", [("period", U32), ("allowed", U32), ("used", U32), ("wait", U32)]),
    0x88: ("POWER", [("millivolts", U16), ("percent", U8), ("flags", U8)]),
    0x89: ("ASKED", [("address", ADDR), ("why", U8)]),
}
BY_NAME = {name: t for t, (name, _) in FRAMES.items()}

SETTINGS = {
    1: ("region", [("value", STR, REGION_MAX)]),
    2: ("role", [("value", U8)]),
    3: ("power", [("value", I8)]),
    4: ("passkey", [("value", U32)]),
}

REQUESTS, ANSWERS, NEWS = (0x01, 0x3F), (0x40, 0x7F), (0x80, 0xBF)

FIXED = {U8: ">B", I8: ">b", U16: ">H", U32: ">I"}


def crc16(data):
    """CRC-16/IBM-3740: polynomial 0x1021, initial value 0xFFFF, not reflected, no final XOR."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (crc << 1 ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def fields_of(t, values):
    fields = list(FRAMES[t][1])
    if t == BY_NAME["SET"]:
        fields += SETTINGS[values["setting"]][1]
    return fields


def encode(kind, seq, /, **values):
    """One frame: its type, its sequence number, and its fields in order."""
    t = BY_NAME[kind]
    out = bytes([t, seq])
    for field in fields_of(t, values):
        v = values[field[0]]
        kind = field[1]
        if kind in FIXED:
            out += struct.pack(FIXED[kind], v)
        elif kind == ADDR:
            assert len(v) == 32
            out += v
        else:
            raw = v.encode("utf-8")
            assert len(raw) <= field[2]
            out += bytes([len(raw)]) + raw
    assert len(out) <= MAX_FRAME
    return out


def decode(frame):
    """The fields of a frame, or the reason a receiver discards it. Bytes past the last field a
    receiver knows are ignored: that is how a later version adds one."""
    if len(frame) < 2:
        return "shorter than a type and a sequence number"
    if len(frame) > MAX_FRAME:
        return "longer than the longest frame"
    if frame[0] not in FRAMES:
        return "a type this version does not define"
    t, at, values = frame[0], 2, {"type": FRAMES[frame[0]][0], "seq": frame[1]}
    fields = list(FRAMES[t][1])
    i = 0
    while i < len(fields):
        name, kind = fields[i][0], fields[i][1]
        if kind in FIXED:
            size = struct.calcsize(FIXED[kind])
            if at + size > len(frame):
                return "a field cut short"
            values[name] = struct.unpack(FIXED[kind], frame[at : at + size])[0]
            at += size
        elif kind == ADDR:
            if at + 32 > len(frame):
                return "a field cut short"
            values[name] = frame[at : at + 32].hex()
            at += 32
        else:
            if at + 1 > len(frame) or at + 1 + frame[at] > len(frame):
                return "a field cut short"
            if frame[at] > fields[i][2]:
                return "a string longer than its field allows"
            try:
                values[name] = frame[at + 1 : at + 1 + frame[at]].decode("utf-8")
            except UnicodeDecodeError:
                return "a string that is not UTF-8"
            at += 1 + frame[at]
        if t == BY_NAME["SET"] and name == "setting":
            if values["setting"] not in SETTINGS:
                return "a setting this version does not define"
            fields += SETTINGS[values["setting"]][1]
        i += 1
    return values


UNKNOWN = ("a type this version does not define", "a setting this version does not define")


def answer(frame, why):
    """What a node answers a request it cannot act on with: ERROR 1 for what it does not know,
    ERROR 2 for what is malformed. None where nothing is answered: a frame too short to have a
    sequence number, and anything outside the request types."""
    if len(frame) < 2 or not REQUESTS[0] <= frame[0] <= REQUESTS[1]:
        return None
    return 1 if why in UNKNOWN else 2


def wrap(frame):
    """A frame as it goes on a byte stream."""
    body = struct.pack(">H", len(frame)) + frame
    return MAGIC + body + struct.pack(">H", crc16(body))


def parse(stream):
    """What a receiver finds in a byte stream: frames, the bytes between them, and whatever is
    left unfinished at the end. A magic that does not start a whole frame with a good CRC is not
    a frame; the receiver looks again from the byte after it."""
    items, text, i = [], bytearray(), 0
    pending = b""

    def flush():
        if text:
            items.append({"text": text.hex()})
            text.clear()

    while i < len(stream):
        if stream[i : i + 2] == MAGIC or (stream[i:] == MAGIC[:1]):
            if i + STREAM_HEAD > len(stream):
                pending = stream[i:]
                break
            n = struct.unpack(">H", stream[i + 2 : i + 4])[0]
            if 2 <= n <= MAX_FRAME:
                end = i + STREAM_HEAD + n + STREAM_TAIL
                if end > len(stream):
                    pending = stream[i:]
                    break
                body = stream[i + 2 : end - 2]
                if struct.unpack(">H", stream[end - 2 : end])[0] == crc16(body):
                    flush()
                    items.append({"frame": body[2:].hex()})
                    i = end
                    continue
        text.append(stream[i])
        i += 1
    flush()
    return items, pending


def self_check():
    assert crc16(b"123456789") == 0x29B1  # the published check value
    assert encode("PING", 7) == b"\x03\x07"
    assert encode("HELLO", 1, version=1) == b"\x01\x01\x01"
    assert encode("SET", 9, setting=3, value=-9) == b"\x05\x09\x03\xf7"
    assert wrap(b"\x03\x07") == bytes.fromhex("f5540002") + b"\x03\x07" + struct.pack(
        ">H", crc16(bytes.fromhex("00020307")))
    longest = encode("MESSAGE", 0, id=0, contact=bytes(32), time=0, flags=0, state=0, reason=0,
                     wait=0, text="x" * TEXT_MAX)
    assert len(longest) == 48 + TEXT_MAX <= MAX_FRAME
    assert len(encode("SEND", 1, ref=0, to=bytes(32), text="x" * TEXT_MAX)) == 39 + TEXT_MAX


# The public keys of RFC 8032's first three Ed25519 test vectors (section 7.1): valid addresses.
ALICE = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
BOB = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
CAROL = bytes.fromhex("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025")


def build():
    self_check()

    examples = [
        ("HELLO", 1, {"version": 1}),
        ("HELLO", 1, {"version": 0}),
        ("SYNC", 2, {"after": 0}),
        ("SYNC", 3, {"after": 0x00000102}),
        ("PING", 4, {}),
        ("SET_TIME", 5, {"time": 1_790_000_000}),
        ("SET", 6, {"setting": 1, "value": "EU868"}),
        ("SET", 7, {"setting": 2, "value": 1}),
        ("SET", 8, {"setting": 3, "value": -9}),
        ("SET", 9, {"setting": 4, "value": 123456}),
        ("SEND", 10, {"ref": 0xC0FFEE01, "to": BOB, "text": "On the ridge by six"}),
        ("SEND", 11, {"ref": 2, "to": BOB, "text": "Ça va? \U0001F426"}),
        ("READ", 12, {"through": 17}),
        ("SAVE_CONTACT", 13, {"address": BOB, "name": "Bob"}),
        ("SAVE_CONTACT", 14, {"address": BOB, "name": ""}),
        ("REMOVE_CONTACT", 15, {"address": BOB}),
        ("END_SESSION", 16, {"address": BOB}),
        ("OK", 4, {}),
        ("ERROR", 15, {"code": 4}),
        ("INFO", 1, {"version": 1, "firmware": "tern 0.1.0 heltec-v3"}),
        ("SYNCED", 2, {}),
        ("QUEUED", 10, {"id": 18}),
        ("SELF", 0, {"address": ALICE, "role": 1, "region": "EU868", "power": 14,
                     "time": 1_790_000_000}),
        ("SELF", 1, {"address": ALICE, "role": 0, "region": "US915", "power": -9, "time": 0}),
        ("CONTACT", 2, {"address": BOB, "session": 1, "name": "Bob"}),
        ("CONTACT_GONE", 3, {"address": BOB}),
        ("MESSAGE", 4, {"id": 17, "contact": BOB, "time": 1_789_999_000, "flags": 1, "state": 4,
                        "reason": 0, "wait": 0, "text": "Where are you?"}),
        ("MESSAGE", 5, {"id": 18, "contact": BOB, "time": 1_790_000_060, "flags": 0, "state": 0,
                        "reason": 3, "wait": 95, "text": "On the ridge by six"}),
        ("STATE", 6, {"id": 18, "state": 1, "reason": 0, "wait": 0}),
        ("STATE", 7, {"id": 18, "state": 2, "reason": 0, "wait": 0}),
        ("NEIGHBOUR", 8, {"routing_id": 0x1D2E3F40, "role": 1, "snr_quarter_db": -38,
                          "heard": 42}),
        ("NEIGHBOUR_GONE", 9, {"routing_id": 0x1D2E3F40}),
        ("AIRTIME", 10, {"period": 3600, "allowed": 360_000, "used": 12_345, "wait": 0}),
        ("AIRTIME", 11, {"period": 0, "allowed": 0, "used": 812, "wait": 0}),
        ("POWER", 12, {"millivolts": 3987, "percent": 81, "flags": 1}),
        ("POWER", 13, {"millivolts": 0, "percent": 255, "flags": 2}),
        ("ASKED", 14, {"address": CAROL, "why": 1}),
        ("ASKED", 15, {"address": CAROL, "why": 2}),
    ]
    frames = []
    for name, seq, values in examples:
        frame = encode(name, seq, **values)
        shown = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in values.items()}
        assert decode(frame) == {"type": name, "seq": seq, **shown}
        frames.append({"type": name, "seq": seq, "fields": shown, "frame": frame.hex(),
                       "stream": wrap(frame).hex()})

    # Bytes past the fields this version defines: a later version's field, read past.
    longer = encode("PING", 4) + b"\x01\x02"
    later = encode("SELF", 0, address=ALICE, role=1, region="EU868", power=14, time=0) + b"\xaa"
    extended = []
    for frame in (longer, later):
        fields = decode(frame)
        assert isinstance(fields, dict)
        extended.append({"frame": frame.hex(), "type": fields.pop("type"),
                         "seq": fields.pop("seq"), "fields": fields})

    hello = encode("HELLO", 1, version=1)
    rejected = []
    for frame in [
        b"\x03",
        hello[:2],
        b"\x00\x01",
        b"\x20\x01",
        b"\xc0\x01",
        b"\x9f\x01",
        encode("SYNC", 2, after=1)[:5],
        encode("SET", 6, setting=1, value="EU868")[:6],
        b"\x05\x06\x09\x00",
        encode("SAVE_CONTACT", 13, address=BOB, name="Bob")[:34],
        encode("SAVE_CONTACT", 13, address=BOB, name="Bob")[:-1],
        encode("SAVE_CONTACT", 13, address=BOB, name="")[:-1] + b"\x20" + b"x" * 32,
        encode("SEND", 10, ref=1, to=BOB, text="")[:-1] + b"\x02\xc3\x28",
        encode("SEND", 10, ref=1, to=BOB, text="")[:-1]
        + bytes([TEXT_MAX + 1]) + b"x" * (TEXT_MAX + 1),
        encode("MESSAGE", 5, id=1, contact=BOB, time=0, flags=0, state=0, reason=0, wait=0,
               text="hi")[:-3],
        encode("END_SESSION", 16, address=BOB)[:-1],
        encode("ASKED", 14, address=CAROL, why=1)[:-1],
    ]:
        why = decode(frame)
        assert isinstance(why, str), frame.hex()
        rejected.append({"why": why, "frame": frame.hex(), "answer": answer(frame, why)})

    ping, ok = encode("PING", 4), encode("OK", 4)
    console = b"status\r\naddress d75a9801...\r\n"
    corrupt = bytearray(wrap(ok))
    corrupt[-1] ^= 0x01
    streams = []
    for why, stream in [
        ("one frame", wrap(ping)),
        ("two frames back to back", wrap(ping) + wrap(ok)),
        ("console text either side", console + wrap(ok) + b"> "),
        ("a frame with its CRC wrong is text", bytes(corrupt) + wrap(ok)),
        ("a length past the longest frame", MAGIC + b"\x00\xb5" + wrap(ok)),
        ("a length too short for a frame", MAGIC + b"\x00\x01\x03" + wrap(ok)),
        ("a magic inside a frame's claimed length", MAGIC + b"\x00\x04" + wrap(ok)),
        ("half a magic", b"\xf5" + wrap(ok)),
        ("a frame that contains the magic", wrap(encode("QUEUED", 10, id=0xF554F554))),
        ("a frame not finished", wrap(ping) + wrap(ok)[:5]),
        ("the start of a magic, last", b"ok\r\n\xf5"),
    ]:
        items, pending = parse(stream)
        streams.append({"why": why, "stream": stream.hex(), "items": items,
                        "pending": pending.hex()})

    # A connection, as both ends see it: who sends what, in order.
    exchange = []
    for side, frame in [
        ("client", encode("HELLO", 1, version=1)),
        ("node", encode("INFO", 1, version=1, firmware="tern 0.1.0 heltec-v3")),
        ("client", encode("SET_TIME", 2, time=1_790_000_000)),
        ("node", encode("OK", 2)),
        ("client", encode("SYNC", 3, after=0)),
        ("node", encode("SELF", 0, address=ALICE, role=1, region="EU868", power=14,
                        time=1_790_000_000)),
        ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
        ("node", encode("MESSAGE", 2, id=17, contact=BOB, time=1_789_999_000, flags=0, state=4,
                        reason=0, wait=0, text="Where are you?")),
        ("node", encode("NEIGHBOUR", 3, routing_id=0x1D2E3F40, role=1, snr_quarter_db=-38,
                        heard=42)),
        ("node", encode("AIRTIME", 4, period=3600, allowed=360_000, used=12_345, wait=0)),
        ("node", encode("POWER", 5, millivolts=3987, percent=81, flags=1)),
        ("node", encode("SYNCED", 3)),
        ("client", encode("READ", 4, through=17)),
        ("node", encode("OK", 4)),
        ("node", encode("MESSAGE", 6, id=17, contact=BOB, time=1_789_999_000, flags=1, state=4,
                        reason=0, wait=0, text="Where are you?")),
        ("client", encode("SEND", 5, ref=0xC0FFEE01, to=BOB, text="On the ridge by six")),
        ("node", encode("QUEUED", 5, id=18)),
        ("node", encode("MESSAGE", 7, id=18, contact=BOB, time=1_790_000_060, flags=0, state=0,
                        reason=1, wait=0, text="On the ridge by six")),
        ("node", encode("STATE", 8, id=18, state=1, reason=0, wait=0)),
        ("node", encode("STATE", 9, id=18, state=2, reason=0, wait=0)),
        # Carol makes first contact, and is refused: she is not a contact.
        ("node", encode("ASKED", 10, address=CAROL, why=1)),
        ("client", encode("SAVE_CONTACT", 6, address=CAROL, name="Carol")),
        ("node", encode("OK", 6)),
        ("node", encode("CONTACT", 11, address=CAROL, session=0, name="Carol")),
        ("client", encode("END_SESSION", 7, address=BOB)),
        ("node", encode("OK", 7)),
        ("node", encode("CONTACT", 12, address=BOB, session=0, name="Bob")),
    ]:
        fields = decode(frame)
        exchange.append({"from": side, "type": fields["type"], "seq": fields["seq"],
                         "frame": frame.hex()})

    # The same node with a client of version 0. Carol is refused after the sync, and the client
    # is not told: the news after it is counted on from the sync's.
    older = []
    for side, frame in [
        ("client", encode("HELLO", 1, version=0)),
        ("node", encode("INFO", 1, version=1, firmware="tern 0.1.0 heltec-v3")),
        ("client", encode("SYNC", 2, after=17)),
        ("node", encode("SELF", 0, address=ALICE, role=1, region="EU868", power=14,
                        time=1_790_000_000)),
        ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
        ("node", encode("NEIGHBOUR", 2, routing_id=0x1D2E3F40, role=1, snr_quarter_db=-38,
                        heard=42)),
        ("node", encode("AIRTIME", 3, period=3600, allowed=360_000, used=12_345, wait=0)),
        ("node", encode("POWER", 4, millivolts=3987, percent=81, flags=1)),
        ("node", encode("SYNCED", 2)),
        ("client", encode("SAVE_CONTACT", 3, address=CAROL, name="Carol")),
        ("node", encode("OK", 3)),
        ("node", encode("CONTACT", 5, address=CAROL, session=0, name="Carol")),
    ]:
        fields = decode(frame)
        older.append({"from": side, "type": fields["type"], "seq": fields["seq"],
                      "frame": frame.hex()})

    return {
        "description": "The companion protocol, version 1 (draft/companion.md). Frames, streams "
        "and addresses are hex; numbers are numbers; strings are text. In frames, frame is the "
        "frame alone, as one BLE write or notification carries it, and stream is the same frame "
        "as it goes on a byte stream. In extended, frame carries bytes past the fields this "
        "version defines, and fields is what a receiver reads from it. In rejected, a receiver "
        "discards frame; answer is the ERROR code a node answers it with, null for none. In "
        "streams, items are what a receiver finds in stream, in order: a frame, or a run of "
        "bytes that is not one, and pending is what it holds at the end waiting for more. "
        "Exchange is one connection, in order; the node refuses first contact from the "
        "third address just before the ASKED in it. Older is a connection to the same node by a "
        "client of version 0; the node refuses that first contact after the sync, before the "
        "client's SAVE_CONTACT. The three addresses are the public keys of RFC 8032's first "
        "three Ed25519 test vectors.",
        "generator": "vectors/tools/companion.py",
        "crc_check": {"input": b"123456789".hex(), "crc": crc16(b"123456789")},
        "frames": frames,
        "extended": extended,
        "rejected": rejected,
        "streams": streams,
        "exchange": exchange,
        "older": older,
    }


def main():
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "generate":
        OUT.write_text(text, encoding="utf-8")
    elif mode == "check":
        if OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT.name} differs from what {Path(__file__).name} computes")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
