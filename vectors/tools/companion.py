#!/usr/bin/env python3
"""Generates and checks the companion protocol's test vectors (draft/companion.md).

    python3 vectors/tools/companion.py generate   # rewrite vectors/companion.json
    python3 vectors/tools/companion.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library; routing ids come from routing.py, beside this file.
Before computing anything it checks its CRC against the published check value for CRC-16/IBM-3740,
its HKDF-Expand against RFC 5869, and its encoder against frames worked by hand.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import hmac
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routing  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "companion.json"

VERSION = 6
MAX_FRAME = 180
MAGIC = b"\xf5\x54"
STREAM_HEAD = 4  # magic and length
STREAM_TAIL = 2  # the CRC

NAME_MAX, TEXT_MAX, FIRMWARE_MAX, REGION_MAX = 31, 128, 31, 15
BOARD_MAX, RELEASE_MAX = 31, 31
UPDATE_CHUNK = 172

# Each field is (name, kind, and for a string or bytes its longest). Kinds: u8, i8, u16, i16, u32,
# i32, addr (32 bytes), gid (a group's id, 8 bytes), digest (a SHA-256, 32 bytes), str (a u8
# length, then that many bytes of UTF-8), raw (bytes: a u8 length, then that many bytes of
# anything).
U8, I8, U16, I16, U32, I32, ADDR, GID, DIGEST, STR, RAW = (
    "u8", "i8", "u16", "i16", "u32", "i32", "addr", "gid", "digest", "str", "raw")
BYTES = {ADDR: 32, GID: 8, DIGEST: 32}

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
    0x20: ("MAKE_GROUP", [("name", STR, NAME_MAX)]),
    0x21: ("LEAVE_GROUP", [("group", GID)]),
    0x22: ("NAME_GROUP", [("group", GID), ("name", STR, NAME_MAX)]),
    0x23: ("SEND_GROUP", [("ref", U32), ("group", GID), ("text", STR, TEXT_MAX)]),
    0x24: ("SEND_INVITE", [("group", GID), ("to", ADDR)]),
    0x25: ("JOIN", [("id", U32)]),
    0x30: ("UPDATE_BEGIN", [("size", U32), ("digest", DIGEST)]),
    0x31: ("UPDATE_DATA", [("offset", U32), ("data", RAW, UPDATE_CHUNK)]),
    0x32: ("UPDATE_END", []),
    0x33: ("SET_POSITION", [("lat", I32), ("lon", I32), ("altitude", I16), ("accuracy", U16),
                            ("age", U16)]),
    0x34: ("SHARE", [("contact", ADDR), ("precision", U8), ("fields", U8), ("interval", U16),
                     ("minutes", U16)]),
    0x35: ("SHARE_GROUP", [("group", GID), ("precision", U8), ("fields", U8), ("interval", U16),
                           ("minutes", U16)]),
    # Answers, node to client.
    0x40: ("OK", []),
    0x41: ("ERROR", [("code", U8)]),
    0x42: ("INFO", [("version", U8), ("firmware", STR, FIRMWARE_MAX), ("board", STR, BOARD_MAX),
                    ("release", STR, RELEASE_MAX)]),
    0x43: ("SYNCED", [("news", U8)]),
    0x44: ("QUEUED", [("id", U32)]),
    0x45: ("MADE", [("group", GID)]),
    0x46: ("UPDATING", [("offset", U32)]),
    # News, node to client.
    0x80: ("SELF", [("address", ADDR), ("role", U8), ("region", STR, REGION_MAX), ("power", I8),
                    ("time", U32), ("cards", U8), ("card_name", STR, NAME_MAX)]),
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
    0x8A: ("GROUP", [("group", GID), ("name", STR, NAME_MAX)]),
    0x8B: ("GROUP_GONE", [("group", GID)]),
    0x8C: ("GROUP_MESSAGE", [("id", U32), ("group", GID), ("from", U32), ("time", U32),
                             ("flags", U8), ("state", U8), ("reason", U8), ("wait", U16),
                             ("text", STR, TEXT_MAX)]),
    0x8D: ("INVITE", [("id", U32), ("contact", ADDR), ("group", GID), ("time", U32),
                      ("flags", U8), ("state", U8), ("reason", U8), ("wait", U16),
                      ("name", STR, NAME_MAX)]),
    0x8E: ("POSITION", [("contact", ADDR), ("precision", U8), ("lat", I32), ("lon", I32),
                        ("altitude", I16), ("accuracy", U8), ("age", U32)]),
    0x8F: ("GROUP_POSITION", [("group", GID), ("from", U32), ("precision", U8), ("lat", I32),
                              ("lon", I32), ("altitude", I16), ("accuracy", U8), ("age", U32)]),
    0x90: ("SHARING", [("contact", ADDR), ("precision", U8), ("fields", U8), ("interval", U16),
                       ("minutes", U16)]),
    0x91: ("GROUP_SHARING", [("group", GID), ("precision", U8), ("fields", U8), ("interval", U16),
                             ("minutes", U16)]),
    0x92: ("CARD", [("address", ADDR), ("heard", U32), ("name", STR, NAME_MAX)]),
    0x93: ("CARD_GONE", [("address", ADDR)]),
}
BY_NAME = {name: t for t, (name, _) in FRAMES.items()}
NEWS_NAMES = {name for t, (name, _) in FRAMES.items() if t >= 0x80}

# Fields a later version added to a frame, and the version that added them. A frame is built and
# read by the version both ends speak, and has none of the fields a later version added.
SINCE = {(0x43, "news"): 3, (0x42, "board"): 4, (0x42, "release"): 4, (0x80, "cards"): 6,
         (0x80, "card_name"): 6}

# Types a later version added, and the version that added them. A receiver of an earlier version
# does not know them: a node answers such a request with ERROR 1, and a client ignores such news.
TYPE_SINCE = {
    0x1A: 1, 0x89: 1,  # END_SESSION, ASKED
    **{t: 2 for t in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x45, 0x8A, 0x8B, 0x8C, 0x8D)},  # groups
    **{t: 4 for t in (0x30, 0x31, 0x32, 0x46)},  # updates
    **{t: 5 for t in (0x33, 0x34, 0x35, 0x8E, 0x8F, 0x90, 0x91)},  # positions
    **{t: 6 for t in (0x92, 0x93)},  # cards
}


def defined(t, speak=VERSION):
    """Whether a connection of version speak defines the type t."""
    return t in FRAMES and TYPE_SINCE.get(t, 0) <= speak

SETTINGS = {
    1: ("region", [("value", STR, REGION_MAX)]),
    2: ("role", [("value", U8)]),
    3: ("power", [("value", I8)]),
    4: ("passkey", [("value", U32)]),
    5: ("cards", [("value", U8)]),
    6: ("card_name", [("value", STR, NAME_MAX)]),
}

# Settings a later version added, and the version that added them. A node of an earlier version, or
# one speaking to a client of an earlier version, answers SET of one with ERROR 1.
SETTING_SINCE = {5: 6, 6: 6}

REQUESTS, ANSWERS, NEWS = (0x01, 0x3F), (0x40, 0x7F), (0x80, 0xBF)

FIXED = {U8: ">B", I8: ">b", U16: ">H", I16: ">h", U32: ">I", I32: ">i"}


def crc16(data):
    """CRC-16/IBM-3740: polynomial 0x1021, initial value 0xFFFF, not reflected, no final XOR."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (crc << 1 ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def group_id(secret):
    """A group's id: HKDF-Expand (RFC 5869) with SHA-256, keyed with the group's secret, for
    eight bytes, which is the first block's first eight."""
    return expand(secret, b"tern v0 group id", 8)


def expand(prk, info, length):
    assert length <= 32
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def fields_of(t, values, speak=VERSION):
    fields = [f for f in FRAMES[t][1] if SINCE.get((t, f[0]), 0) <= speak]
    if t == BY_NAME["SET"]:
        fields += SETTINGS[values["setting"]][1]
    return fields


def encode(kind, seq, /, *, speak=VERSION, **values):
    """One frame: its type, its sequence number, and its fields in order, as a connection of
    version speak carries it."""
    t = BY_NAME[kind]
    out = bytes([t, seq])
    for field in fields_of(t, values, speak):
        v = values[field[0]]
        kind = field[1]
        if kind in FIXED:
            out += struct.pack(FIXED[kind], v)
        elif kind in BYTES:
            assert len(v) == BYTES[kind]
            out += v
        elif kind == RAW:
            assert len(v) <= field[2]
            out += bytes([len(v)]) + v
        else:
            raw = v.encode("utf-8")
            assert len(raw) <= field[2]
            out += bytes([len(raw)]) + raw
    assert len(out) <= MAX_FRAME
    return out


def decode(frame, speak=VERSION):
    """The fields of a frame, or the reason a receiver discards it, on a connection of version
    speak. Bytes past the last field a receiver knows are ignored: that is how a later version
    adds one."""
    if len(frame) < 2:
        return "shorter than a type and a sequence number"
    if len(frame) > MAX_FRAME:
        return "longer than the longest frame"
    if not defined(frame[0], speak):
        return "a type this version does not define"
    t, at, values = frame[0], 2, {"type": FRAMES[frame[0]][0], "seq": frame[1]}
    fields = [f for f in FRAMES[t][1] if SINCE.get((t, f[0]), 0) <= speak]
    i = 0
    while i < len(fields):
        name, kind = fields[i][0], fields[i][1]
        if kind in FIXED:
            size = struct.calcsize(FIXED[kind])
            if at + size > len(frame):
                return "a field cut short"
            values[name] = struct.unpack(FIXED[kind], frame[at : at + size])[0]
            at += size
        elif kind in BYTES:
            if at + BYTES[kind] > len(frame):
                return "a field cut short"
            values[name] = frame[at : at + BYTES[kind]].hex()
            at += BYTES[kind]
        elif kind == RAW:
            if at + 1 > len(frame) or at + 1 + frame[at] > len(frame):
                return "a field cut short"
            if frame[at] > fields[i][2]:
                return "bytes longer than their field allows"
            values[name] = frame[at + 1 : at + 1 + frame[at]].hex()
            at += 1 + frame[at]
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
            setting = values["setting"]
            if setting not in SETTINGS or SETTING_SINCE.get(setting, 0) > speak:
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
    # RFC 5869, test case 1, cut to one block.
    assert expand(bytes.fromhex("077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5"),
                  bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 32).hex() == (
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf")
    assert encode("PING", 7) == b"\x03\x07"
    assert encode("SYNCED", 3, news=6) == b"\x43\x03\x06"
    assert encode("SYNCED", 3, speak=2) == b"\x43\x03"
    assert decode(b"\x43\x03", speak=2) == {"type": "SYNCED", "seq": 3}
    assert encode("HELLO", 1, version=1) == b"\x01\x01\x01"
    assert len(encode("GROUP_MESSAGE", 0, id=0, group=bytes(8), time=0, flags=0, state=0,
                      reason=0, wait=0, text="x" * TEXT_MAX, **{"from": 0})) == 28 + TEXT_MAX
    assert encode("SET", 9, setting=3, value=-9) == b"\x05\x09\x03\xf7"
    assert wrap(b"\x03\x07") == bytes.fromhex("f5540002") + b"\x03\x07" + struct.pack(
        ">H", crc16(bytes.fromhex("00020307")))
    longest = encode("MESSAGE", 0, id=0, contact=bytes(32), time=0, flags=0, state=0, reason=0,
                     wait=0, text="x" * TEXT_MAX)
    assert len(longest) == 48 + TEXT_MAX <= MAX_FRAME
    assert len(encode("SEND", 1, ref=0, to=bytes(32), text="x" * TEXT_MAX)) == 39 + TEXT_MAX
    assert len(encode("UPDATE_DATA", 1, offset=0, data=bytes(UPDATE_CHUNK))) == 179 <= MAX_FRAME
    assert encode("INFO", 1, speak=3, version=4, firmware="t", board="b", release="1") == (
        b"\x42\x01\x04\x01t")
    assert encode("SET", 9, setting=6, value="Ada") == b"\x05\x09\x06\x03Ada"
    assert decode(b"\x05\x09\x05\x01", speak=5) == UNKNOWN[1]
    me = dict(address=bytes(32), role=0, region="", power=0, time=0, cards=1, card_name="A")
    assert encode("SELF", 0, **me) == encode("SELF", 0, speak=5, **me) + b"\x01\x01A"
    assert len(encode("CARD", 0, address=bytes(32), heard=0, name="x" * NAME_MAX)) == 39 + NAME_MAX


# The public keys of RFC 8032's first three Ed25519 test vectors (section 7.1): valid addresses.
ALICE = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
BOB = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
CAROL = bytes.fromhex("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025")
# And of the fourth, TEST 1024: the node that sends the card the vectors' node holds.
DAVE = bytes.fromhex("278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e")
TRAIL = "Trail crew · ask me"  # the name Dave's cards carry, as one of cards.json's does

# Two groups' secrets: the one the node makes in the exchange, and the one it is invited to.
MADE_SECRET = bytes(range(16))
INVITED_SECRET = bytes.fromhex("c4" * 16)
HUT, RIDGE = group_id(MADE_SECRET), group_id(INVITED_SECRET)

# The image an update sends: 400 bytes, so two whole chunks and a short one. A node in the
# vectors runs any image whose digest is right; a real one also checks that it is an image for
# its hardware.
IMAGE = bytes((i * 151 + 7) & 0xFF for i in range(400))
DIGEST_OF_IMAGE = hashlib.sha256(IMAGE).digest()
FIRMWARE = dict(firmware="tern 0.2.0 heltec-v3", board="heltec-v3", release="0.2.0")

# Positions, in 10^-7 degree. The client's own is positions.json's summit. Bob's is the centre of
# the cell at precision 16 that positions.json's harbour is in, as a node reports one it holds.
SUMMIT = dict(lat=458_325_000, lon=68_644_000)
BOB_AT = dict(precision=16, lat=603_945_922, lon=52_871_704)
NO_ALTITUDE = -32768


def info(speak=VERSION):
    """The node's INFO, as a client of version speak is sent it."""
    return encode("INFO", 1, speak=speak, version=VERSION, **FIRMWARE)


def build():
    self_check()

    examples = [
        ("HELLO", 1, {"version": 6}),
        ("HELLO", 1, {"version": 5}),
        ("HELLO", 1, {"version": 4}),
        ("HELLO", 1, {"version": 3}),
        ("HELLO", 1, {"version": 2}),
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
        ("MAKE_GROUP", 17, {"name": "Hut"}),
        ("LEAVE_GROUP", 18, {"group": HUT}),
        ("NAME_GROUP", 19, {"group": RIDGE, "name": "Ridge walkers"}),
        ("SEND_GROUP", 20, {"ref": 0xC0FFEE02, "group": HUT, "text": "Anyone at the hut?"}),
        ("SEND_INVITE", 21, {"group": HUT, "to": BOB}),
        ("JOIN", 22, {"id": 22}),
        ("UPDATE_BEGIN", 23, {"size": len(IMAGE), "digest": DIGEST_OF_IMAGE}),
        ("UPDATE_DATA", 24, {"offset": 0, "data": IMAGE[:UPDATE_CHUNK]}),
        ("UPDATE_DATA", 25, {"offset": 2 * UPDATE_CHUNK, "data": IMAGE[2 * UPDATE_CHUNK :]}),
        ("UPDATE_END", 26, {}),
        ("SET_POSITION", 27, {**SUMMIT, "altitude": 4806, "accuracy": 4, "age": 3}),
        ("SET_POSITION", 28, {"lat": -336_183_000, "lon": -704_517_000, "altitude": NO_ALTITUDE,
                              "accuracy": 0, "age": 600}),
        ("SHARE", 29, {"contact": BOB, "precision": 20, "fields": 3, "interval": 900,
                       "minutes": 60}),
        ("SHARE", 30, {"contact": BOB, "precision": 0, "fields": 0, "interval": 0, "minutes": 0}),
        ("SHARE_GROUP", 31, {"group": RIDGE, "precision": 12, "fields": 0, "interval": 300,
                             "minutes": 0}),
        ("SET", 32, {"setting": 5, "value": 1}),
        ("SET", 33, {"setting": 5, "value": 0}),
        ("SET", 34, {"setting": 6, "value": "Ada · hut warden"}),
        ("SET", 35, {"setting": 6, "value": ""}),
        ("OK", 4, {}),
        ("ERROR", 15, {"code": 4}),
        ("INFO", 1, {"version": 4, **FIRMWARE}),
        ("INFO", 1, {"version": 4, "firmware": "tern (built by hand)", "board": "",
                     "release": ""}),
        ("SYNCED", 2, {"news": 6}),
        ("QUEUED", 10, {"id": 18}),
        ("MADE", 17, {"group": HUT}),
        ("UPDATING", 23, {"offset": 0}),
        ("UPDATING", 23, {"offset": 2 * UPDATE_CHUNK}),
        ("ERROR", 24, {"code": 10}),
        ("ERROR", 26, {"code": 11}),
        ("ERROR", 29, {"code": 12}),
        ("SELF", 0, {"address": ALICE, "role": 1, "region": "EU868", "power": 14,
                     "time": 1_790_000_000, "cards": 1, "card_name": "Ada · hut warden"}),
        ("SELF", 1, {"address": ALICE, "role": 0, "region": "US915", "power": -9, "time": 0,
                     "cards": 0, "card_name": ""}),
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
        ("GROUP", 16, {"group": HUT, "name": "Hut"}),
        ("GROUP", 17, {"group": RIDGE, "name": ""}),
        ("GROUP_GONE", 18, {"group": HUT}),
        ("GROUP_MESSAGE", 19, {"id": 20, "group": HUT, "from": 0, "time": 1_790_000_120,
                               "flags": 0, "state": 0, "reason": 4, "wait": 22,
                               "text": "Anyone at the hut?"}),
        ("GROUP_MESSAGE", 20, {"id": 21, "group": HUT, "from": routing.rid(BOB),
                               "time": 1_790_000_150, "flags": 1, "state": 4, "reason": 0,
                               "wait": 0, "text": "Two of us"}),
        ("INVITE", 21, {"id": 19, "contact": BOB, "group": HUT, "time": 1_790_000_100,
                        "flags": 0, "state": 2, "reason": 0, "wait": 0, "name": "Hut"}),
        ("INVITE", 22, {"id": 22, "contact": BOB, "group": RIDGE, "time": 1_790_000_200,
                        "flags": 0, "state": 4, "reason": 0, "wait": 0, "name": "Ridge"}),
        ("POSITION", 23, {"contact": BOB, **BOB_AT, "altitude": NO_ALTITUDE, "accuracy": 0,
                          "age": 40}),
        ("POSITION", 24, {"contact": BOB, "precision": 0, "lat": 0, "lon": 0, "altitude": 0,
                          "accuracy": 0, "age": 0}),
        ("GROUP_POSITION", 25, {"group": RIDGE, "from": routing.rid(CAROL), "precision": 24,
                                "lat": 458_325_040, "lon": 68_644_058, "altitude": 4806,
                                "accuracy": 4, "age": 12}),
        ("SHARING", 26, {"contact": BOB, "precision": 20, "fields": 3, "interval": 900,
                         "minutes": 60}),
        ("SHARING", 27, {"contact": BOB, "precision": 0, "fields": 0, "interval": 0, "minutes": 0}),
        ("GROUP_SHARING", 28, {"group": RIDGE, "precision": 12, "fields": 0, "interval": 300,
                               "minutes": 0}),
        ("CARD", 29, {"address": DAVE, "heard": 1260, "name": TRAIL}),
        ("CARD", 30, {"address": DAVE, "heard": 86_399, "name": ""}),
        ("CARD_GONE", 31, {"address": DAVE}),
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
    later = encode("SELF", 0, address=ALICE, role=1, region="EU868", power=14, time=0, cards=0,
                   card_name="") + b"\xaa"
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
        b"\x2f\x01",
        b"\xc0\x01",
        b"\x9f\x01",
        encode("SYNC", 2, after=1)[:5],
        encode("SYNCED", 3, news=6)[:-1],
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
        encode("LEAVE_GROUP", 18, group=HUT)[:-1],
        encode("MAKE_GROUP", 17, name="")[:-1] + b"\x20" + b"x" * 32,
        encode("SEND_GROUP", 20, ref=1, group=HUT, text="")[:-1] + b"\x02\xc3\x28",
        encode("SEND_INVITE", 21, group=HUT, to=BOB)[:-1],
        encode("JOIN", 22, id=22)[:-1],
        encode("GROUP", 16, group=HUT, name="Hut")[:-1],
        encode("INVITE", 22, id=22, contact=BOB, group=RIDGE, time=0, flags=0, state=4, reason=0,
               wait=0, name="Ridge")[:-6],
        encode("UPDATE_BEGIN", 23, size=1, digest=DIGEST_OF_IMAGE)[:-1],
        encode("UPDATE_DATA", 24, offset=0, data=IMAGE[:10])[:-1],
        encode("UPDATE_DATA", 24, offset=0, data=b"")[:-1] + bytes([UPDATE_CHUNK + 1])
        + IMAGE[: UPDATE_CHUNK + 1],
        encode("UPDATING", 23, offset=0)[:-1],
        encode("INFO", 1, version=4, **FIRMWARE)[:-1],
        encode("SET_POSITION", 27, **SUMMIT, altitude=0, accuracy=0, age=0)[:-1],
        encode("SHARE", 29, contact=BOB, precision=20, fields=0, interval=900, minutes=0)[:-1],
        encode("POSITION", 23, contact=BOB, **BOB_AT, altitude=0, accuracy=0, age=0)[:-1],
        encode("SET", 32, setting=5, value=1)[:-1],
        encode("SET", 34, setting=6, value="")[:-1] + b"\x20" + b"x" * 32,
        encode("SET", 34, setting=6, value="")[:-1] + b"\x02\xc3\x28",
        encode("CARD", 29, address=DAVE, heard=1260, name="")[:-1],
        encode("CARD", 29, address=DAVE, heard=1260, name="")[:-1] + b"\x02\xc3\x28",
        encode("CARD_GONE", 31, address=DAVE)[:-1],
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
    self_ = dict(address=ALICE, role=1, region="EU868", power=14, time=1_790_000_000, cards=0,
                 card_name="")
    neighbour = dict(routing_id=0x1D2E3F40, role=1, snr_quarter_db=-38, heard=42)
    airtime = dict(period=3600, allowed=360_000, used=12_345, wait=0)
    power = dict(millivolts=3987, percent=81, flags=1)
    where = dict(id=17, contact=BOB, time=1_789_999_000, state=4, reason=0, wait=0,
                 text="Where are you?")
    ridge = dict(id=18, contact=BOB, time=1_790_000_060, flags=0, text="On the ridge by six")
    bob = routing.rid(BOB)
    invite = dict(id=19, contact=BOB, group=HUT, time=1_790_000_100, flags=0, name="Hut")
    anyone = dict(id=20, group=HUT, time=1_790_000_120, flags=0, text="Anyone at the hut?",
                  **{"from": 0})
    two = dict(id=21, group=HUT, time=1_790_000_150, state=4, reason=0, wait=0, text="Two of us",
               **{"from": bob})
    invited = dict(id=22, contact=BOB, group=RIDGE, time=1_790_000_200, state=4, reason=0,
                   wait=0, name="Ridge")

    def connection(frames, speak=VERSION):
        out = []
        for side, frame in frames:
            fields = decode(frame, speak)
            if isinstance(fields, str):
                # A request the client must not send, refused: named by the latest version.
                assert side == "client" and fields in UNKNOWN, fields
                fields = decode(frame)
            out.append({"from": side, "type": fields["type"], "seq": fields["seq"],
                        "frame": frame.hex()})
        return out

    exchange = connection([
        ("client", encode("HELLO", 1, version=VERSION)),
        ("node", info()),
        ("client", encode("SET_TIME", 2, time=1_790_000_000)),
        ("node", encode("OK", 2)),
        ("client", encode("SYNC", 3, after=0)),
        ("node", encode("SELF", 0, **self_)),
        ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
        ("node", encode("MESSAGE", 2, flags=0, **where)),
        ("node", encode("NEIGHBOUR", 3, **neighbour)),
        ("node", encode("CARD", 4, address=DAVE, heard=1260, name=TRAIL)),
        ("node", encode("AIRTIME", 5, **airtime)),
        ("node", encode("POWER", 6, **power)),
        ("node", encode("SYNCED", 3, news=7)),
        ("client", encode("READ", 4, through=17)),
        ("node", encode("OK", 4)),
        ("node", encode("MESSAGE", 7, flags=1, **where)),
        ("client", encode("SEND", 5, ref=0xC0FFEE01, to=BOB, text="On the ridge by six")),
        ("node", encode("QUEUED", 5, id=18)),
        ("node", encode("MESSAGE", 8, state=0, reason=1, wait=0, **ridge)),
        ("node", encode("STATE", 9, id=18, state=1, reason=0, wait=0)),
        ("node", encode("STATE", 10, id=18, state=2, reason=0, wait=0)),
        # Carol makes first contact, and is refused: she is not a contact.
        ("node", encode("ASKED", 11, address=CAROL, why=1)),
        ("client", encode("SAVE_CONTACT", 6, address=CAROL, name="Carol")),
        ("node", encode("OK", 6)),
        ("node", encode("CONTACT", 12, address=CAROL, session=0, name="Carol")),
        # A group is made, Bob is invited to it, and a message is written to it.
        ("client", encode("MAKE_GROUP", 7, name="Hut")),
        ("node", encode("MADE", 7, group=HUT)),
        ("node", encode("GROUP", 13, group=HUT, name="Hut")),
        ("client", encode("SEND_INVITE", 8, group=HUT, to=BOB)),
        ("node", encode("QUEUED", 8, id=19)),
        ("node", encode("INVITE", 14, state=0, reason=1, wait=0, **invite)),
        ("node", encode("STATE", 15, id=19, state=1, reason=0, wait=0)),
        ("node", encode("STATE", 16, id=19, state=2, reason=0, wait=0)),
        ("client", encode("SEND_GROUP", 9, ref=0xC0FFEE02, group=HUT, text="Anyone at the hut?")),
        ("node", encode("QUEUED", 9, id=20)),
        ("node", encode("GROUP_MESSAGE", 17, state=0, reason=0, wait=0, **anyone)),
        ("node", encode("STATE", 18, id=20, state=1, reason=0, wait=0)),
        # Bob answers in the group, and invites this node to another.
        ("node", encode("GROUP_MESSAGE", 19, flags=0, **two)),
        ("node", encode("INVITE", 20, flags=0, **invited)),
        ("client", encode("JOIN", 10, id=22)),
        ("node", encode("OK", 10)),
        ("node", encode("GROUP", 21, group=RIDGE, name="Ridge")),
        ("client", encode("NAME_GROUP", 11, group=RIDGE, name="Ridge walkers")),
        ("node", encode("OK", 11)),
        ("node", encode("GROUP", 22, group=RIDGE, name="Ridge walkers")),
        ("client", encode("READ", 12, through=22)),
        ("node", encode("OK", 12)),
        ("node", encode("GROUP_MESSAGE", 23, flags=1, **two)),
        ("node", encode("INVITE", 24, flags=1, **invited)),
        ("client", encode("LEAVE_GROUP", 13, group=HUT)),
        ("node", encode("OK", 13)),
        ("node", encode("GROUP_GONE", 25, group=HUT)),
        # The client gives the node its position, and the user shares it with Bob for an hour.
        # Bob's position arrives. A precision past 24 is refused, and sharing with Bob is
        # turned off again.
        ("client", encode("SET_POSITION", 14, **SUMMIT, altitude=4806, accuracy=4, age=3)),
        ("node", encode("OK", 14)),
        ("client", encode("SHARE", 15, contact=BOB, precision=20, fields=0, interval=900,
                          minutes=60)),
        ("node", encode("OK", 15)),
        ("node", encode("SHARING", 26, contact=BOB, precision=20, fields=0, interval=900,
                        minutes=60)),
        ("node", encode("POSITION", 27, contact=BOB, **BOB_AT, altitude=NO_ALTITUDE, accuracy=0,
                        age=40)),
        ("client", encode("SHARE_GROUP", 16, group=RIDGE, precision=25, fields=0, interval=300,
                          minutes=0)),
        ("node", encode("ERROR", 16, code=3)),
        ("client", encode("SHARE", 17, contact=BOB, precision=0, fields=0, interval=0,
                          minutes=0)),
        ("node", encode("OK", 17)),
        ("node", encode("SHARING", 28, contact=BOB, precision=0, fields=0, interval=0,
                        minutes=0)),
        ("client", encode("END_SESSION", 18, address=BOB)),
        ("node", encode("OK", 18)),
        ("node", encode("CONTACT", 29, address=BOB, session=0, name="Bob")),
        # The user names the node's cards and turns them on; a value that is neither on nor off is
        # refused. A newer card from Dave arrives, and the user saves him as a contact from it,
        # under a name of their own. Cards are turned off again, and a day later the node forgets
        # Dave's card.
        ("client", encode("SET", 19, setting=6, value="Ada · hut warden")),
        ("node", encode("OK", 19)),
        ("node", encode("SELF", 30, **{**self_, "card_name": "Ada · hut warden"})),
        ("client", encode("SET", 20, setting=5, value=1)),
        ("node", encode("OK", 20)),
        ("node", encode("SELF", 31, **{**self_, "cards": 1, "card_name": "Ada · hut warden"})),
        ("client", encode("SET", 21, setting=5, value=2)),
        ("node", encode("ERROR", 21, code=3)),
        ("node", encode("CARD", 32, address=DAVE, heard=0, name=TRAIL)),
        ("client", encode("SAVE_CONTACT", 22, address=DAVE, name="Dave (trail crew)")),
        ("node", encode("OK", 22)),
        ("node", encode("CONTACT", 33, address=DAVE, session=0, name="Dave (trail crew)")),
        ("client", encode("SET", 23, setting=5, value=0)),
        ("node", encode("OK", 23)),
        ("node", encode("SELF", 34, **{**self_, "card_name": "Ada · hut warden"})),
        ("node", encode("CARD_GONE", 35, address=DAVE)),
    ])

    counted = [f["seq"] for f in exchange if f["type"] in NEWS_NAMES]
    assert counted == list(range(len(counted))), counted

    # The same node with clients of earlier versions. To one of version 0, Carol is refused after
    # the sync, and the client is not told: the news after it is counted on from the sync's. To
    # one of version 1, the node holds the group it made, and Bob's group message and invite come
    # after the sync: the client is told of none of them, and the message it then sends has an
    # id three past the last it saw. To one of version 2, holding what the exchange begins with,
    # the sync ends with a SYNCED as version 2 has it, without the count.
    older = [
        {"version": 0, "frames": connection([
            ("client", encode("HELLO", 1, version=0)),
            ("node", info(0)),
            ("client", encode("SYNC", 2, after=17)),
            ("node", encode("SELF", 0, speak=0, **self_)),
            ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
            ("node", encode("NEIGHBOUR", 2, **neighbour)),
            ("node", encode("AIRTIME", 3, **airtime)),
            ("node", encode("POWER", 4, **power)),
            ("node", encode("SYNCED", 2, speak=0)),
            ("client", encode("SAVE_CONTACT", 3, address=CAROL, name="Carol")),
            ("node", encode("OK", 3)),
            ("node", encode("CONTACT", 5, address=CAROL, session=0, name="Carol")),
        ], 0)},
        {"version": 1, "frames": connection([
            ("client", encode("HELLO", 1, version=1)),
            ("node", info(1)),
            ("client", encode("SYNC", 2, after=0)),
            ("node", encode("SELF", 0, speak=1, **{**self_, "time": 1_790_000_130})),
            ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
            ("node", encode("CONTACT", 2, address=CAROL, session=0, name="Carol")),
            ("node", encode("MESSAGE", 3, flags=1, **where)),
            ("node", encode("MESSAGE", 4, state=2, reason=0, wait=0, **ridge)),
            ("node", encode("NEIGHBOUR", 5, **neighbour)),
            ("node", encode("AIRTIME", 6, **airtime)),
            ("node", encode("POWER", 7, **power)),
            ("node", encode("SYNCED", 2, speak=1)),
            ("client", encode("SEND", 3, ref=0xC0FFEE03, to=BOB, text="Coming down")),
            ("node", encode("QUEUED", 3, id=23)),
            ("node", encode("MESSAGE", 8, id=23, contact=BOB, time=1_790_000_300, flags=0,
                            state=0, reason=1, wait=0, text="Coming down")),
            ("client", encode("MAKE_GROUP", 4, name="Hut")),
            ("node", encode("ERROR", 4, code=1)),
        ], 1)},
        {"version": 2, "frames": connection([
            ("client", encode("HELLO", 1, version=2)),
            ("node", info(2)),
            ("client", encode("SYNC", 2, after=0)),
            ("node", encode("SELF", 0, speak=2, **self_)),
            ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
            ("node", encode("MESSAGE", 2, flags=0, **where)),
            ("node", encode("NEIGHBOUR", 3, **neighbour)),
            ("node", encode("AIRTIME", 4, **airtime)),
            ("node", encode("POWER", 5, **power)),
            ("node", encode("SYNCED", 2, speak=2)),
        ], 2)},
    ]
    # Clients of versions 3 and 4, to a node that also holds a position from Bob and shares its
    # own with him: neither is told of either. Each sends a request its version does not define.
    for speak, refused in [
        (3, encode("UPDATE_BEGIN", 3, size=len(IMAGE), digest=DIGEST_OF_IMAGE)),
        (4, encode("SHARE", 3, contact=BOB, precision=0, fields=0, interval=0, minutes=0)),
    ]:
        older.append({"version": speak, "frames": connection([
            ("client", encode("HELLO", 1, version=speak)),
            ("node", info(speak)),
            ("client", encode("SYNC", 2, after=0)),
            ("node", encode("SELF", 0, speak=speak, **self_)),
            ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
            ("node", encode("MESSAGE", 2, flags=0, **where)),
            ("node", encode("NEIGHBOUR", 3, **neighbour)),
            ("node", encode("AIRTIME", 4, **airtime)),
            ("node", encode("POWER", 5, **power)),
            ("node", encode("SYNCED", 2, news=6, speak=speak)),
            ("client", refused),
            ("node", encode("ERROR", 3, code=1)),
        ], speak)})

    # A client of version 5, to the node as the exchange begins, holding Dave's card: the sync sends
    # no CARD, and a SELF without cards and card_name. The client's last request names a setting its
    # version does not define.
    older.append({"version": 5, "frames": connection([
        ("client", encode("HELLO", 1, version=5)),
        ("node", info(5)),
        ("client", encode("SYNC", 2, after=0)),
        ("node", encode("SELF", 0, speak=5, **self_)),
        ("node", encode("CONTACT", 1, address=BOB, session=1, name="Bob")),
        ("node", encode("MESSAGE", 2, flags=0, **where)),
        ("node", encode("NEIGHBOUR", 3, **neighbour)),
        ("node", encode("AIRTIME", 4, **airtime)),
        ("node", encode("POWER", 5, **power)),
        ("node", encode("SYNCED", 2, news=6, speak=5)),
        ("client", encode("SET", 3, setting=5, value=1)),
        ("node", encode("ERROR", 3, code=1)),
    ], 5)})

    # Frames a later version defines, as a receiver of an earlier version reads them: a type it
    # does not know. A node answers such a request with ERROR 1; a client ignores such news.
    unknown_to_older = []
    for name, speak, values in [
        ("END_SESSION", 0, {"address": BOB}),
        ("ASKED", 0, {"address": CAROL, "why": 1}),
        ("MAKE_GROUP", 1, {"name": "Hut"}),
        ("GROUP", 1, {"group": HUT, "name": "Hut"}),
        ("UPDATE_BEGIN", 3, {"size": len(IMAGE), "digest": DIGEST_OF_IMAGE}),
        ("UPDATE_END", 3, {}),
        ("UPDATING", 3, {"offset": 0}),
        ("SHARE", 4, {"contact": BOB, "precision": 20, "fields": 0, "interval": 900,
                      "minutes": 60}),
        ("SET_POSITION", 4, {**SUMMIT, "altitude": 4806, "accuracy": 4, "age": 3}),
        ("POSITION", 4, {"contact": BOB, **BOB_AT, "altitude": NO_ALTITUDE, "accuracy": 0,
                         "age": 40}),
        ("SHARING", 4, {"contact": BOB, "precision": 20, "fields": 0, "interval": 900,
                        "minutes": 60}),
        ("SET", 5, {"setting": 5, "value": 1}),
        ("SET", 5, {"setting": 6, "value": TRAIL}),
        ("CARD", 5, {"address": DAVE, "heard": 1260, "name": TRAIL}),
        ("CARD_GONE", 5, {"address": DAVE}),
    ]:
        frame = encode(name, 5, **values)
        assert isinstance(decode(frame), dict)
        why = decode(frame, speak)
        assert why in UNKNOWN, (name, speak, why)
        unknown_to_older.append({"type": name, "version": speak, "frame": frame.hex(),
                                 "why": why, "answer": answer(frame, why)})

    # An update over two connections: the link is lost after the second chunk, and the client goes
    # on from where the node says. Then a node refusing what it should, on one connection.
    def start():
        return [
            ("client", encode("HELLO", 1, version=VERSION)),
            ("node", info()),
            ("client", encode("SET_TIME", 2, time=1_790_000_000)),
            ("node", encode("OK", 2)),
            ("client", encode("SYNC", 3, after=0)),
            ("node", encode("SELF", 0, **self_)),
            ("node", encode("AIRTIME", 1, **airtime)),
            ("node", encode("POWER", 2, **power)),
            ("node", encode("SYNCED", 3, news=3)),
        ]

    size, chunk = len(IMAGE), UPDATE_CHUNK

    def data(seq, at, n=chunk, image=IMAGE):
        return encode("UPDATE_DATA", seq, offset=at, data=image[at : at + n])

    begin = encode("UPDATE_BEGIN", 4, size=size, digest=DIGEST_OF_IMAGE)
    update = [
        connection(start() + [
            ("client", begin),
            ("node", encode("UPDATING", 4, offset=0)),
            ("client", data(5, 0)),
            ("node", encode("OK", 5)),
            ("client", data(6, chunk)),
            ("node", encode("OK", 6)),
        ]),
        connection(start() + [
            ("client", begin),
            ("node", encode("UPDATING", 4, offset=2 * chunk)),
            ("client", data(5, 2 * chunk)),
            ("node", encode("OK", 5)),
            ("client", encode("UPDATE_END", 6)),
            ("node", encode("OK", 6)),
        ]),
    ]
    wrong = hashlib.sha256(b"").digest()
    refusals = connection([
        ("client", encode("HELLO", 1, version=VERSION)),
        ("node", info()),
        ("client", data(2, 0)),
        ("node", encode("ERROR", 2, code=10)),
        ("client", encode("UPDATE_END", 3)),
        ("node", encode("ERROR", 3, code=10)),
        ("client", encode("UPDATE_BEGIN", 4, size=0, digest=DIGEST_OF_IMAGE)),
        ("node", encode("ERROR", 4, code=3)),
        ("client", encode("UPDATE_BEGIN", 5, size=size, digest=wrong)),
        ("node", encode("UPDATING", 5, offset=0)),
        ("client", data(6, 0)),
        ("node", encode("OK", 6)),
        ("client", data(7, 0)),
        ("node", encode("OK", 7)),
        ("client", data(8, 300)),
        ("node", encode("ERROR", 8, code=10)),
        ("client", data(9, chunk)),
        ("node", encode("OK", 9)),
        ("client", encode("UPDATE_DATA", 10, offset=2 * chunk, data=bytes(chunk))),
        ("node", encode("ERROR", 10, code=3)),
        ("client", encode("UPDATE_DATA", 11, offset=2 * chunk, data=b"")),
        ("node", encode("ERROR", 11, code=3)),
        ("client", encode("UPDATE_END", 12)),
        ("node", encode("ERROR", 12, code=10)),
        ("client", data(13, 2 * chunk)),
        ("node", encode("OK", 13)),
        ("client", encode("UPDATE_END", 14)),
        ("node", encode("ERROR", 14, code=11)),
        ("client", encode("UPDATE_END", 15)),
        ("node", encode("ERROR", 15, code=10)),
    ])

    group_ids = [{"group_secret": g.hex(), "group": group_id(g).hex()}
                 for g in (MADE_SECRET, INVITED_SECRET, bytes(16), bytes([0xFF] * 16))]

    return {
        "description": "The companion protocol, version 6 (draft/companion.md). Frames, streams, "
        "addresses and group ids are hex; numbers are numbers; strings are text. In frames, "
        "frame is the frame alone, as one BLE write or notification carries it, and stream is "
        "the same frame as it goes on a byte stream. In extended, frame carries bytes past the "
        "fields this version defines, and fields is what a receiver reads from it. In rejected, "
        "a receiver discards frame; answer is the ERROR code a node answers it with, null for "
        "none. In unknown_to_older, frame is of a type, or names a setting, that version does "
        "not define: a node "
        "speaking it answers ERROR answer, and a client speaking it ignores news and discards an answer (null). "
        "In streams, items are what a receiver finds in stream, in order: a frame, or a "
        "run of bytes that is not one, and pending is what it holds at the end waiting for more. "
        "In group_ids, group is the id of the group whose secret is group_secret. Exchange is "
        "one connection, in order. In it the node refuses first contact from the third address "
        "just before the ASKED; the group it makes has the secret made, where a node in use "
        "draws one; and after its own group message is sent it receives a message to that group "
        "from the second address's routing id, and then an invite from that address to the "
        "group whose secret is invited. After it leaves the first group, it receives a position "
        "from the second address, just before its POSITION. It holds a card from the fourth "
        "address from the start, received 1260 seconds before the sync; after the CONTACT that "
        "follows END_SESSION it accepts a newer card from that address, with the same name, "
        "just before the CARD that says so, and forgets it just before the CARD_GONE. Older "
        "holds connections to the same node by clients of "
        "earlier versions. To the client of version 0 it holds what the exchange begins with, "
        "and refuses that first contact after the sync, before the client's SAVE_CONTACT. To "
        "the client of version 1 it holds what the exchange has before its JOIN but for the "
        "group message and the invite received, which come after the sync and before the "
        "client's SEND; the client's last request is one its version does not define, which a "
        "client must not send, and the node answers it as it would any other it does not know "
        "from that client. To the client of version 2 it holds what the exchange begins with, "
        "and its SYNCED is version 2's, without news. To the clients of versions 3 and 4 it "
        "holds what the exchange begins with, a position from the second address, and sharing "
        "with that address: the sync sends neither, and the node refuses the request each "
        "client's version does not define, which it must not send. To the client of version 5 "
        "it holds what the exchange begins with, and the sync sends no card; the client's last "
        "request names a setting its version does not define. Positions are in units of "
        "10^-7 degree. Each connection's frames are read by the "
        "version its client speaks, and each client of an earlier version is sent an INFO "
        "without board and release. Update is one update of image, whose SHA-256 is "
        "image_digest, over two connections to a node that holds only itself: the link is lost "
        "after the first connection's last frame, and the node keeps what it was sent. "
        "Refusals is one connection to a node with no update under way, given an image of the "
        "same size whose digest is not its own. The four addresses are the public keys of RFC "
        "8032's first four Ed25519 test vectors (section 7.1: TEST 1, 2, 3 and 1024).",
        "generator": "vectors/tools/companion.py",
        "crc_check": {"input": b"123456789".hex(), "crc": crc16(b"123456789")},
        "made": MADE_SECRET.hex(),
        "invited": INVITED_SECRET.hex(),
        "frames": frames,
        "extended": extended,
        "rejected": rejected,
        "streams": streams,
        "group_ids": group_ids,
        "exchange": exchange,
        "older": older,
        "unknown_to_older": unknown_to_older,
        "image": IMAGE.hex(),
        "image_digest": DIGEST_OF_IMAGE.hex(),
        "update": update,
        "refusals": refusals,
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
