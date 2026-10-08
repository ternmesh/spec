#!/usr/bin/env python3
"""Generates and checks the test vectors for frames that follow routes (draft/forwarding.md).

    python3 vectors/tools/forwarding.py generate   # rewrite vectors/forwarding.json
    python3 vectors/tools/forwarding.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Floors come from routing.py and airtimes from phy.py,
beside this file.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phy  # noqa: E402
import routing  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "forwarding.json"

HDR_MESSAGE, HDR_ACK = 0x48, 0x50
# First contact's four frames (draft/first-contact.md), and how long each is: the head, a tag,
# for the first the routing id it came from, and the handshake's message.
CONTACT_LEN = {0x51: 56, 0x52: 60, 0x53: 80, 0x54: 24}
RESERVED = (0, 0xFFFFFFFF)
HEAD, TAG = 11, 4
ACK_LEN = HEAD + TAG + 4
MESSAGE_MIN = HEAD + TAG + 8
AT_DEST = 7
HOP_MAX = 32
POWER_MARGIN = 10
STEP = 3
RETRY_JITTER = 4
HEAD_WAIT = 13


def head(h):
    return struct.pack(">BBbII", h["hdr"], h["hops"], h["power"], h["next"], h["destination"])


def accepted(frame):
    """Whether a receiver takes a frame at all."""
    if len(frame) > 255 or not frame or frame[0] not in (HDR_MESSAGE, HDR_ACK, *CONTACT_LEN):
        return False
    if frame[0] in CONTACT_LEN and len(frame) != CONTACT_LEN[frame[0]]:
        return False
    if frame[0] == HDR_ACK and len(frame) != ACK_LEN:
        return False
    if frame[0] == HDR_MESSAGE and len(frame) < MESSAGE_MIN:
        return False
    _, _, _, nxt, dst = struct.unpack(">BBbII", frame[:HEAD])
    return nxt not in RESERVED and dst not in RESERVED


def ends(sent, heard):
    """Whether hearing one frame ends the hop of another this node sent: both whole frames."""
    passed = sent[AT_DEST:] == heard[AT_DEST:] and sent[0] == heard[0] and heard[1] + 1 == sent[1]
    answered = (
        sent[0] == HDR_MESSAGE
        and heard[0] == HDR_ACK
        and heard[HEAD : HEAD + TAG] == sent[HEAD : HEAD + TAG]
    )
    return passed or answered


def hop_heard(frame):
    """Whether a node that has sent a frame listens for the hop to succeed. On the last hop of an
    acknowledgement or a first-contact frame there is nothing to hear."""
    _, _, _, nxt, dst = struct.unpack(">BBbII", frame[:HEAD])
    return frame[0] == HDR_MESSAGE or nxt != dst


def clamp(sixteenths, lowest, full):
    return max(lowest, min(full, -(-sixteenths // 16)))


def needs(power, snr_quarters, sf, lowest, full):
    """What a frame must go at for the node a frame came from to hear it."""
    return clamp(routing.floor_next(None, power, snr_quarters, sf) + 16 * POWER_MARGIN, lowest, full)


def power(neighbour, back, tries, full):
    """What a frame goes at: for its neighbour and the node before, and louder each try."""
    return min(full, max(neighbour, back if back is not None else neighbour) + STEP * tries)


def longest_wait(sf, bw_hz, length):
    """The longest a frame sent again waits first, in nanoseconds: RETRY_JITTER of its airtimes."""
    return RETRY_JITTER * phy.airtime_ns(sf, bw_hz, length)


def symbol_ns(sf, bw_hz):
    return (1 << sf) * 1_000_000_000 // bw_hz


def head_wait(sf, bw_hz):
    """How long a preamble with no header after it holds a node, in nanoseconds."""
    return (phy.PREAMBLE + HEAD_WAIT) * symbol_ns(sf, bw_hz)


def receiving(sf, bw_hz, events, at):
    """Whether a radio that reported events, as (time, what) in order, is receiving at a time."""
    found, header = None, False

    def held(header):
        return phy.airtime_ns(sf, bw_hz, 255) if header else head_wait(sf, bw_hz)

    for when, what in events:
        if when > at:
            break
        if found is not None and when - found >= held(header):
            found = None  # what it was on ran out before this
        if what == "preamble":
            found, header = when, False
        elif what == "header":
            found, header = (when if found is None else found), True
        else:  # the frame ended, or the node began to send
            found = None
    return found is not None and at - found < held(header)


def listen_cases(sf, bw_hz):
    """Each way a reception can go, asked just inside and just outside each bound."""
    sym, wait, longest = symbol_ns(sf, bw_hz), head_wait(sf, bw_hz), phy.airtime_ns(sf, bw_hz, 255)
    start, frame = 1_000_000, phy.airtime_ns(sf, bw_hz, 40)
    found = start + 5 * sym
    lines = [
        ([], [0, start]),
        ([(found, "preamble")], [found - 1, found, found + wait - 1, found + wait]),
        ([(found, "preamble"), (found + 16 * sym, "header")],
         [found + wait, found + longest - 1, found + longest]),
        ([(found, "preamble"), (found + 16 * sym, "header"), (start + frame, "end")],
         [found + 16 * sym, start + frame - 1, start + frame]),
        ([(found, "preamble"), (found + 18 * sym, "end")], [found + 18 * sym - 1, found + 18 * sym]),
        ([(found, "preamble"), (found + 3 * sym, "sent")], [found + 3 * sym - 1, found + 3 * sym]),
        ([(found, "preamble"), (found + 9 * sym, "preamble")],
         [found + wait, found + 9 * sym + wait - 1, found + 9 * sym + wait]),
        ([(found, "header")], [found - 1, found, found + longest - 1, found + longest]),
        # A header that comes after the wait for one ran out is a frame of its own.
        ([(found, "preamble"), (found + wait + 10 * sym, "header")],
         [found + wait, found + wait + 10 * sym, found + longest,
          found + wait + 10 * sym + longest - 1, found + wait + 10 * sym + longest]),
        ([(found, "preamble"), (found + wait, "header")], [found + longest, found + wait + longest - 1]),
        ([(found, "preamble"), (found + wait - 1, "header")], [found + longest - 1, found + longest]),
        ([(found, "preamble"), (found + 16 * sym, "header"), (start + frame, "end"),
          (start + frame + 20 * sym, "preamble")],
         [start + frame + 20 * sym - 1, start + frame + 20 * sym, start + frame + 20 * sym + wait]),
    ]
    return [
        {
            "spreading_factor": sf, "bandwidth_hz": bw_hz,
            "events": [{"at_ns": when, "radio": what} for when, what in events],
            "asks": [{"at_ns": at, "receiving": receiving(sf, bw_hz, events, at)} for at in asks],
        }
        for events, asks in lines
    ]


def self_check():
    # A 35-byte frame at SF9 and 500 kHz is on the air for 69.888 ms by phy.py, which checks its
    # own arithmetic against values worked by hand; four of them is the longest wait.
    assert phy.airtime_ns(9, 500_000, 35) == 69_888_000 and longest_wait(9, 500_000, 35) == 279_552_000
    f = head({"hdr": 0x48, "hops": 31, "power": -4, "next": 0x01020304, "destination": 0xA0B0C0D0})
    assert f.hex() == "481ffc01020304a0b0c0d0"
    assert accepted(f + bytes(12)) and not accepted(f + bytes(3))
    # SF9 demodulates down to -12.5 dB. Sent at 2 dBm and heard at +11.5 dB, a frame was 24 dB
    # louder than it needed to be: its sender is reached at -22 dBm, and with the margin at -12.
    assert needs(2, 46, 9, -9, 22) == -9 and needs(2, 46, 9, -20, 22) == -12
    assert power(5, None, 2, 22) == 11 and power(5, 9, 0, 22) == 9 and power(20, None, 1, 22) == 22
    # At SF9 and 500 kHz a symbol is 1.024 ms, so a preamble of 16 and 13 more is 29.696 ms: a
    # bare preamble found at 5 ms holds a node until 34.696 ms, and a header for a 255-byte frame.
    assert head_wait(9, 500_000) == 29_696_000
    bare, whole = [(5_000_000, "preamble")], [(5_000_000, "preamble"), (9_000_000, "header")]
    assert receiving(9, 500_000, bare, 34_695_999) and not receiving(9, 500_000, bare, 34_696_000)
    assert receiving(9, 500_000, whole, 34_696_000) and not receiving(9, 500_000, bare, 4_999_999)
    assert not receiving(9, 500_000, whole + [(60_000_000, "end")], 60_000_000)
    # A header 40 ms after that preamble comes when its wait has run out, and so is held from
    # itself: a 255-byte frame is on the air 320.768 ms, which from the preamble ends at 325.768.
    late = bare + [(45_000_000, "header")]
    assert phy.airtime_ns(9, 500_000, 255) == 320_768_000
    assert receiving(9, 500_000, late, 325_768_000) and not receiving(9, 500_000, late, 365_768_000)


def build():
    self_check()
    heads = []
    for h, body in [
        ({"hdr": 0x48, "hops": 32, "power": 22, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x30, 0x30 + 4 + 5 + 8))),
        ({"hdr": 0x48, "hops": 1, "power": -9, "next": 1, "destination": 0xFFFFFFFE},
         bytes(range(0x80, 0x80 + 4 + 8))),
        ({"hdr": 0x50, "hops": 31, "power": 0, "next": 0x0A0B0C0D, "destination": 0x1D2E3F40},
         bytes(range(0x30, 0x34)) + bytes.fromhex("c0ffee01")),
        ({"hdr": 0x51, "hops": 32, "power": 14, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x30, 0x30 + 4 + 4 + 37))),
        ({"hdr": 0x52, "hops": 30, "power": 2, "next": 0x0A0B0C0D, "destination": 0x30313233},
         bytes(range(0x40, 0x40 + 4 + 45))),
        ({"hdr": 0x53, "hops": 32, "power": 22, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x50, 0x50 + 4 + 65))),
        ({"hdr": 0x54, "hops": 2, "power": -9, "next": 0x30313233, "destination": 0x30313233},
         bytes(range(0x60, 0x60 + 4 + 9))),
    ]:
        frame = head(h) + body
        assert accepted(frame)
        heads.append({**h, "tag": body[:TAG].hex(), "frame": frame.hex()})

    good = {"hdr": 0x48, "hops": 32, "power": 14, "next": 7, "destination": 9}
    rejected = []
    for why, frame in [
        ("shorter than a head and a tag", head(good) + bytes(3)),
        ("a message with a tag and no check", head(good) + bytes(4)),
        ("a message a byte short of its check", head(good) + bytes(11)),
        ("not a frame of this section's", head({**good, "hdr": 0x59}) + bytes(12)),
        ("an acknowledgement too long", head({**good, "hdr": 0x50}) + bytes(9)),
        ("an acknowledgement too short", head({**good, "hdr": 0x50}) + bytes(7)),
        ("for every neighbour", head({**good, "next": 0xFFFFFFFF}) + bytes(12)),
        ("for neighbour zero", head({**good, "next": 0}) + bytes(12)),
        ("for destination zero", head({**good, "destination": 0}) + bytes(12)),
        ("for every destination", head({**good, "destination": 0xFFFFFFFF}) + bytes(12)),
        ("a first message_1 a byte long", head({**good, "hdr": 0x51}) + bytes(46)),
        ("a first message_1 with no routing id it came from", head({**good, "hdr": 0x51}) + bytes(41)),
        ("a first-contact message_2 a byte short", head({**good, "hdr": 0x52}) + bytes(48)),
        ("a first-contact message_3 of message_2's length", head({**good, "hdr": 0x53}) + bytes(49)),
        ("a first-contact message_4 a byte long", head({**good, "hdr": 0x54}) + bytes(14)),
        ("a first-contact message_4 for neighbour zero", head({**good, "hdr": 0x54, "next": 0}) + bytes(13)),
        ("first contact has no message_5", head({**good, "hdr": 0x55}) + bytes(13)),
    ]:
        assert not accepted(frame)
        rejected.append({"why": why, "frame": frame.hex()})

    tag, other = bytes.fromhex("30313233"), bytes.fromhex("40414243")
    body = tag + bytes(range(0x60, 0x6D))  # the tag, five bytes of message and the check

    def message(hops, destination=9, rest=body, nxt=7, pw=14):
        return head({"hdr": 0x48, "hops": hops, "power": pw, "next": nxt, "destination": destination}) + rest

    def ack(hops, destination=77, t=tag, nxt=7):
        return head({"hdr": 0x50, "hops": hops, "power": 3, "next": nxt, "destination": destination}) + t + bytes(4)

    def contact(n, hops, destination=9, nxt=7, fill=0x70):
        h = {"hdr": 0x50 + n, "hops": hops, "power": 6, "next": nxt, "destination": destination}
        return head(h) + tag + bytes(range(fill, fill + CONTACT_LEN[0x50 + n] - HEAD - TAG))

    hops = []
    for why, s, h in [
        ("passed on", message(20), message(19, nxt=8, pw=-2)),
        ("another copy of what it sent", message(20), message(20)),
        ("passed on twice: not by its neighbour", message(20), message(18)),
        ("another tag", message(20), message(19, rest=other + body[4:])),
        ("the same tag and another message", message(20), message(19, rest=tag + bytes(13))),
        ("the same tag and a longer message", message(20), message(19, rest=body + b"\x00")),
        ("for another node", message(20), message(19, destination=10)),
        ("acknowledged", message(20), ack(32)),
        ("acknowledged, heard further off", message(20), ack(5)),
        ("another message acknowledged", message(20), ack(32, t=other)),
        ("an acknowledgement passed on", ack(20, destination=9), ack(19, destination=9, nxt=8)),
        ("an acknowledgement is not ended by a message", ack(20, destination=9), message(19)),
        ("hops do not wrap", message(0), message(255)),
        ("first contact passed on", contact(1, 20), contact(1, 19, nxt=8)),
        ("first contact, another copy of what it sent", contact(3, 20), contact(3, 20)),
        ("first contact, another message with the same tag", contact(2, 20), contact(2, 19, fill=0x71)),
        ("first contact is not ended by an acknowledgement with its tag", contact(1, 20), ack(32)),
        ("first contact is not ended by its answer", contact(1, 20), contact(2, 32, destination=77)),
        ("a message is not ended by first contact with its tag", message(20), contact(4, 19)),
    ]:
        assert accepted(s) and accepted(h)
        hops.append({"why": why, "sent": s.hex(), "heard": h.hex(), "ends": ends(s, h)})

    waits = []
    for why, f in [
        ("a message", message(20)),
        ("a message to its destination: its acknowledgement is listened for", message(20, nxt=9)),
        ("an acknowledgement on its way", ack(20)),
        ("an acknowledgement to the node it is for", ack(20, nxt=77)),
        ("first contact on its way", contact(1, 32)),
        ("first contact to the node it is for", contact(1, 32, nxt=9)),
        ("the last frame of first contact to the node it is for", contact(4, 3, nxt=9)),
        ("the last frame of first contact on its way", contact(4, 3)),
    ]:
        assert accepted(f)
        waits.append({"why": why, "sent": f.hex(), "listens": hop_heard(f)})

    backs = [
        {
            "power": p, "snr_quarter_db": q, "spreading_factor": sf, "lowest": lo, "full": hi,
            "needs": needs(p, q, sf, lo, hi),
        }
        for p, q, sf, lo, hi in [
            (2, 46, 9, -9, 22), (2, 46, 9, -20, 22), (22, -50, 9, -9, 22), (22, -49, 9, -9, 22),
            (22, -47, 9, -9, 20), (14, 3, 7, -9, 22), (-9, 127, 7, -9, 22), (10, -30, 7, -9, 14),
            (0, 1, 12, -9, 22),
        ]
    ]

    powers = [
        {"neighbour": n, "back": b, "try": t, "full": hi, "power": power(n, b, t, hi)}
        for n, b, t, hi in [
            (5, None, 0, 22), (5, None, 1, 22), (5, None, 2, 22), (5, 9, 0, 22), (5, 9, 2, 22),
            (9, 5, 0, 22), (20, None, 1, 22), (-9, -9, 0, 22), (22, None, 2, 22), (12, 14, 1, 14),
        ]
    ]

    # A frame sent again waits a random time, so a case can give only its bound: the least and
    # the largest frames, and one between, on each profile and on the slowest setting, for a hop
    # sent again and for a message started again by its source.
    agains = [
        {
            "again": which, "spreading_factor": sf, "bandwidth_hz": bw, "length": n,
            "airtime_ns": phy.airtime_ns(sf, bw, n), "longest_ns": longest_wait(sf, bw, n),
        }
        for sf, bw in [(9, 500_000), (7, 125_000), (12, 125_000)]
        for which, lengths in [("hop", (ACK_LEN, MESSAGE_MIN, 35, 255)), ("source", (MESSAGE_MIN, 35, 255))]
        for n in lengths
    ]

    listens = [c for sf, bw in [(9, 500_000), (7, 125_000), (12, 125_000)] for c in listen_cases(sf, bw)]

    return {
        "description": "Frames that follow routes, draft 0 (draft/forwarding.md). Routing ids "
        "are numbers; frames and tags are hex. In hops, sent is the frame the node sent and "
        "heard the one it then received. In waits, listens is whether a node that has sent the "
        "frame listens for its hop to succeed, and sends it again if it does not. In backs, power is what a frame was sent at in dBm and "
        "snr_quarter_db what it was heard at, and needs is what an answer must go at for its "
        "sender to hear it, between the node's lowest and full power. In powers, neighbour is "
        "what Routes gives for the neighbour, its boost included, back is what the node the "
        "frame came from needs or null for a frame that answers none, and try counts from 0. In "
        "agains, a frame of length bytes is sent again at that spreading factor and bandwidth, "
        "with the profiles' preamble and coding rate (vectors/phy.json), by a hop that heard "
        "nothing of it (hop) or by its source with no acknowledgement (source): airtime_ns is "
        "its time on the air and longest_ns the longest it may wait first. In listens, a radio at "
        "that spreading factor and bandwidth finds a preamble or a header, says a frame has ended "
        "(end), or is given a frame to send (sent) at the times in events, and receiving is "
        "whether a node may not start to send at each time in asks, every event at or before "
        "that time having happened.",
        "generator": "vectors/tools/forwarding.py",
        "heads": heads,
        "rejected": rejected,
        "hops": hops,
        "waits": waits,
        "backs": backs,
        "powers": powers,
        "agains": agains,
        "listens": listens,
    }


def main():
    text = json.dumps(build(), indent=2) + "\n"
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
