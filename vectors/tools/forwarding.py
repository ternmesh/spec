#!/usr/bin/env python3
"""Generates and checks the test vectors for frames that follow routes (draft/forwarding.md).

    python3 vectors/tools/forwarding.py generate   # rewrite vectors/forwarding.json
    python3 vectors/tools/forwarding.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Floors come from routing.py, beside this file.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routing  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "forwarding.json"

HDR_MESSAGE, HDR_ACK = 0x48, 0x50
RESERVED = (0, 0xFFFFFFFF)
HEAD, TAG = 11, 4
ACK_LEN = HEAD + TAG + 4
HOP_MAX = 32
POWER_MARGIN = 10
STEP = 3


def head(h):
    return struct.pack(">BBbII", h["hdr"], h["hops"], h["power"], h["next"], h["destination"])


def accepted(frame):
    """Whether a receiver takes a frame at all."""
    if len(frame) < HEAD + TAG or len(frame) > 255 or frame[0] not in (HDR_MESSAGE, HDR_ACK):
        return False
    if frame[0] == HDR_ACK and len(frame) != ACK_LEN:
        return False
    _, _, _, nxt, dst = struct.unpack(">BBbII", frame[:HEAD])
    return nxt not in RESERVED and dst not in RESERVED


def ends(sent, heard):
    """Whether hearing one frame ends the hop of another this node sent."""
    passed = (
        heard["hdr"] == sent["hdr"]
        and heard["destination"] == sent["destination"]
        and heard["tag"] == sent["tag"]
        and heard["hops"] + 1 == sent["hops"]
    )
    answered = (
        sent["hdr"] == HDR_MESSAGE and heard["hdr"] == HDR_ACK and heard["tag"] == sent["tag"]
    )
    return passed or answered


def clamp(sixteenths, lowest, full):
    return max(lowest, min(full, -(-sixteenths // 16)))


def needs(power, snr_quarters, sf, lowest, full):
    """What a frame must go at for the node a frame came from to hear it."""
    return clamp(routing.floor_next(None, power, snr_quarters, sf) + 16 * POWER_MARGIN, lowest, full)


def power(neighbour, back, tries, full):
    """What a frame goes at: for its neighbour and the node before, and louder each try."""
    return min(full, max(neighbour, back if back is not None else neighbour) + STEP * tries)


def self_check():
    f = head({"hdr": 0x48, "hops": 31, "power": -4, "next": 0x01020304, "destination": 0xA0B0C0D0})
    assert f.hex() == "481ffc01020304a0b0c0d0"
    assert accepted(f + bytes(12)) and not accepted(f + bytes(3))
    # SF9 demodulates down to -12.5 dB. Sent at 2 dBm and heard at +11.5 dB, a frame was 24 dB
    # louder than it needed to be: its sender is reached at -22 dBm, and with the margin at -12.
    assert needs(2, 46, 9, -9, 22) == -9 and needs(2, 46, 9, -20, 22) == -12
    assert power(5, None, 2, 22) == 11 and power(5, 9, 0, 22) == 9 and power(20, None, 1, 22) == 22


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
    ]:
        frame = head(h) + body
        assert accepted(frame)
        heads.append({**h, "tag": body[:TAG].hex(), "frame": frame.hex()})

    good = {"hdr": 0x48, "hops": 32, "power": 14, "next": 7, "destination": 9}
    rejected = []
    for why, frame in [
        ("shorter than a head and a tag", head(good) + bytes(3)),
        ("not a frame of this section's", head({**good, "hdr": 0x59}) + bytes(12)),
        ("an acknowledgement too long", head({**good, "hdr": 0x50}) + bytes(9)),
        ("an acknowledgement too short", head({**good, "hdr": 0x50}) + bytes(7)),
        ("for every neighbour", head({**good, "next": 0xFFFFFFFF}) + bytes(12)),
        ("for neighbour zero", head({**good, "next": 0}) + bytes(12)),
        ("for destination zero", head({**good, "destination": 0}) + bytes(12)),
        ("for every destination", head({**good, "destination": 0xFFFFFFFF}) + bytes(12)),
    ]:
        assert not accepted(frame)
        rejected.append({"why": why, "frame": frame.hex()})

    sent = {"hdr": 0x48, "hops": 20, "destination": 9, "tag": "30313233"}
    ack = {"hdr": 0x50, "hops": 20, "destination": 9, "tag": "30313233"}
    hops = []
    for s, h in [
        (sent, {**sent, "hops": 19}),  # passed on
        (sent, {**sent, "hops": 20}),  # another copy of what it sent
        (sent, {**sent, "hops": 18}),  # passed on twice: not by its neighbour
        (sent, {**sent, "hops": 19, "tag": "30313234"}),
        (sent, {**sent, "hops": 19, "destination": 10}),
        (sent, {"hdr": 0x50, "hops": 32, "destination": 77, "tag": "30313233"}),  # acknowledged
        (sent, {"hdr": 0x50, "hops": 5, "destination": 77, "tag": "30313233"}),
        (sent, {"hdr": 0x50, "hops": 32, "destination": 77, "tag": "40414243"}),
        (ack, {**ack, "hops": 19}),
        (ack, {"hdr": 0x48, "hops": 19, "destination": 9, "tag": "30313233"}),
        ({**sent, "hops": 0}, {**sent, "hops": 255}),  # hops do not wrap
    ]:
        hops.append({"sent": s, "heard": h, "ends": ends(s, h)})

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

    return {
        "description": "Frames that follow routes, draft 0 (draft/forwarding.md). Routing ids "
        "are numbers; frames and tags are hex. In hops, sent is what the node sent and heard "
        "what it then received. In backs, power is what a frame was sent at in dBm and "
        "snr_quarter_db what it was heard at, and needs is what an answer must go at for its "
        "sender to hear it, between the node's lowest and full power. In powers, neighbour is "
        "what Routes gives for the neighbour, its boost included, back is what the node the "
        "frame came from needs or null for a frame that answers none, and try counts from 0.",
        "generator": "vectors/tools/forwarding.py",
        "heads": heads,
        "rejected": rejected,
        "hops": hops,
        "backs": backs,
        "powers": powers,
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
