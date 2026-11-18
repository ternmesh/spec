#!/usr/bin/env python3
"""Generates and checks the test vectors for leaves that sleep (draft/sleeping.md).

    python3 vectors/tools/sleeping.py generate   # rewrite vectors/sleeping.json
    python3 vectors/tools/sleeping.py check      # fail if the file differs from what this computes

Needs the Python `cryptography` package, for the announces' signatures, through routing.py, whose
routing ids, promise encoding and blinded signatures it uses: every announce is signed by the
routing key of a seed of first-contact.json, as routing.py's are, and checked by the
cryptography package's own Ed25519. Before computing anything it checks its arithmetic against
values worked by hand.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routing  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "sleeping.json"

HDR_HELD, HDR_POLL, HDR_POLL_ANSWER = 0x55, 0x5D, 0x5E
POLL_LEN, POLL_ANSWER_LEN, HELD_LEN = 15, 14, 15
KIND_SLEEP = 0x04
FLAG_SLEEPS = 0x08
RESERVED = (0, 0xFFFFFFFF)

WAKE_MIN_S, WAKE_MAX_S = 30, 3600
LISTEN_MIN_S = 2
HOLD_EXTRA_S = 60
# Forwarding's (draft/forwarding.md).
ACK_WAIT_MS, ACK_FACTOR = 5000, 4


def wake_ok(code):
    """Whether a wake time, in the promise's encoding, is one a poll may give."""
    s = routing.promise_read(code)
    return s is not None and WAKE_MIN_S <= s <= WAKE_MAX_S


def poll(p):
    return struct.pack(
        ">BIIHHBb", HDR_POLL, p["sender"], p["keeper"], p["id"], p["wake"], p["listen"], p["power"]
    )


def poll_answer(a):
    return struct.pack(
        ">BIIHBBb", HDR_POLL_ANSWER, a["sender"], a["leaf"], a["id"], a["margin"], a["held"],
        a["power"],
    )


def held(h):
    return struct.pack(">BBbIII", HDR_HELD, 0, h["power"], h["next"], h["destination"], h["tag"])


def read(frame, own):
    """The fields of a poll, a poll answer or a held notice, or None if a node with routing id own
    MUST discard it."""
    if not frame:
        return None
    if frame[0] == HDR_POLL and len(frame) == POLL_LEN:
        _, sender, keeper, id_, wake, listen, power = struct.unpack(">BIIHHBb", frame)
        if sender in RESERVED or sender == own or keeper in RESERVED:
            return None
        if not wake_ok(wake) or listen < LISTEN_MIN_S:
            return None
        return {"sender": sender, "keeper": keeper, "id": id_, "wake": wake, "listen": listen,
                "power": power}
    if frame[0] == HDR_POLL_ANSWER and len(frame) == POLL_ANSWER_LEN:
        _, sender, leaf, id_, margin, n, power = struct.unpack(">BIIHBBb", frame)
        if sender in RESERVED or sender == own or leaf in RESERVED:
            return None
        return {"sender": sender, "leaf": leaf, "id": id_, "margin": margin, "held": n,
                "power": power}
    if frame[0] == HDR_HELD and len(frame) == HELD_LEN:
        _, _, power, nxt, dst, tag = struct.unpack(">BBbIII", frame)
        if nxt in RESERVED or dst in RESERVED:
            return None
        return {"power": power, "next": nxt, "destination": dst, "tag": tag}
    return None


def announce(a, seed):
    """An announce as draft/routing.md has it, with bit 3 of flags and keeper when a["sleeps"]."""
    flags = (
        (routing.FLAG_RELAY if a["relay"] else 0)
        | (routing.FLAG_STARTING if a["starting"] else 0)
        | (routing.FLAG_KEY if a["carries_key"] else 0)
        | (FLAG_SLEEPS if a["sleeps"] else 0)
    )
    out = struct.pack(
        ">BIHHBHHbBB", routing.HDR_ANNOUNCE, a["sender"], a["number"], a["seq"], flags,
        a["promise"], a["round"], a["power"], len(a["neighbours"]), len(a["routes"]),
    )
    if a["sleeps"]:
        out += struct.pack(">I", a["keeper"])
    if a["carries_key"]:
        out += routing.blinded_secret(seed)[2]
    for n in a["neighbours"]:
        out += struct.pack(">IB", n["id"], n["margin"])
    for r in a["routes"]:
        out += struct.pack(">IHH", r["destination"], r["seq"], r["metric"])
    out += routing.blinded_sign(seed, routing.LABEL + out)
    assert len(out) <= 255
    return out


def announce_taken(frame, own):
    """Whether a node with routing id own, holding no key for the sender, takes the announce."""
    if len(frame) < 17 + routing.SIG or len(frame) > 255 or frame[0] != routing.HDR_ANNOUNCE:
        return False
    flags, h, r = frame[9], frame[15], frame[16]
    known = routing.FLAG_RELAY | routing.FLAG_STARTING | routing.FLAG_KEY | FLAG_SLEEPS
    if flags & ~known:
        return False
    s, carries = bool(flags & FLAG_SLEEPS), bool(flags & routing.FLAG_KEY)
    if len(frame) != 17 + 4 * s + 32 * carries + 5 * h + 8 * r + routing.SIG:
        return False
    sender = struct.unpack(">I", frame[1:5])[0]
    if sender in RESERVED or sender == own:
        return False
    if s and (flags & routing.FLAG_RELAY):
        return False
    if s and struct.unpack(">I", frame[17:21])[0] in RESERVED:
        return False
    if not carries:
        return False  # it holds no key to check it with
    cards, valid_address = routing._crypto()
    k = frame[17 + 4 * s : 49 + 4 * s]
    if not valid_address(k) or routing.key_id(k) != sender:
        return False
    try:
        cards.Ed25519PublicKey.from_public_bytes(k).verify(
            frame[-routing.SIG :], routing.LABEL + frame[: -routing.SIG]
        )
    except (cards.InvalidSignature, ValueError):
        return False
    return True


def sleep_content(wake):
    return struct.pack(">BH", KIND_SLEEP, wake)


def sleep_valid(content):
    if len(content) != 3 or content[0] != KIND_SLEEP:
        return False
    wake = struct.unpack(">H", content[1:])[0]
    return wake == 0 or wake_ok(wake)


def holds(since_ms, listen_s):
    """Whether a keeper holds a frame for its leaf, since_ms after it received the leaf's last
    frame, the leaf's last poll having given listen_s: it does while the leaf is not awake."""
    return since_ms >= 1000 * listen_s


def hold_for_s(wake):
    return 2 * routing.promise_read(wake) + HOLD_EXTRA_S


def wait_ms(metric, wake):
    return ACK_WAIT_MS + ACK_FACTOR * metric + 1000 * routing.promise_read(wake) + 1000 * LISTEN_MIN_S


def self_check():
    """Values worked by hand."""
    assert poll({"sender": 1, "keeper": 2, "id": 3, "wake": 300, "listen": 2, "power": -1}) == bytes.fromhex(
        "5d" "00000001" "00000002" "0003" "012c" "02" "ff"
    )
    assert held({"power": 14, "next": 0x0A0B0C0D, "destination": 7, "tag": 0xDEADBEEF}) == bytes.fromhex(
        "55" "00" "0e" "0a0b0c0d" "00000007" "deadbeef"
    )
    assert wake_ok(30) and wake_ok(3600) and wake_ok(0x8000 | 60) and not wake_ok(0x8000 | 61)
    assert not wake_ok(29) and not wake_ok(0xFFFF)
    assert hold_for_s(300) == 660 and hold_for_s(0x8000 | 60) == 7260
    assert wait_ms(70, 300) == 5000 + 280 + 300000 + 2000
    assert holds(2000, 2) and not holds(1999, 2)


def build():
    self_check()
    cards, _ = routing._crypto()
    seeds = cards.seeds()
    signers = [cards.address(x) for x in seeds]
    leaf, keeper, other = (routing.rid(x) for x in signers)

    polls = [
        {"sender": leaf, "keeper": keeper, "id": 0x1234, "wake": 300, "listen": 2, "power": 2},
        {"sender": leaf, "keeper": keeper, "id": 0xFFFF, "wake": 0x8000 | 60, "listen": 255,
         "power": -9},
        {"sender": leaf, "keeper": keeper, "id": 0, "wake": 30, "listen": 10, "power": 22},
    ]
    answers = [
        {"sender": keeper, "leaf": leaf, "id": 0x1234, "margin": 140, "held": 0, "power": 2},
        {"sender": keeper, "leaf": leaf, "id": 0xFFFF, "margin": 255, "held": 255, "power": -9},
    ]
    notices = [
        {"power": 14, "next": other, "destination": leaf, "tag": 0x01020304},
        {"power": -9, "next": other, "destination": leaf, "tag": 0xFFFFFFFF},
    ]
    for x in polls:
        x["frame"] = poll(x).hex()
    for x in answers:
        x["frame"] = poll_answer(x).hex()
    for x in notices:
        x["frame"] = held(x).hex()
    for group in (polls, answers, notices):
        for x in group:
            fields = read(bytes.fromhex(x["frame"]), own=other)
            assert fields == {k: v for k, v in x.items() if k != "frame"}, x

    good = bytes.fromhex(polls[0]["frame"])
    p = dict(polls[0])
    p.pop("frame")
    rejected = [
        {"why": "too short", "frame": good[:-1].hex()},
        {"why": "too long", "frame": (good + b"\x00").hex()},
        {"why": "wake under WAKE_MIN", "frame": poll({**p, "wake": 29}).hex()},
        {"why": "wake over WAKE_MAX", "frame": poll({**p, "wake": 0x8000 | 61}).hex()},
        {"why": "wake not a wake time", "frame": poll({**p, "wake": 0xFFFF}).hex()},
        {"why": "listen under LISTEN_MIN", "frame": poll({**p, "listen": 1}).hex()},
        {"why": "keeper reserved", "frame": poll({**p, "keeper": 0xFFFFFFFF}).hex()},
        {"why": "sender reserved", "frame": poll({**p, "sender": 0}).hex()},
        {"why": "answer naming a reserved leaf",
         "frame": poll_answer({**answers[0], "leaf": 0}).hex()},
        {"why": "held notice too long", "frame": (bytes.fromhex(notices[0]["frame"]) + b"\x00").hex()},
    ]
    for x in rejected:
        assert read(bytes.fromhex(x["frame"]), own=other) is None, x

    announces = [
        {"sender": leaf, "number": 9, "seq": 4, "relay": False, "starting": False,
         "carries_key": True, "sleeps": True, "keeper": keeper, "promise": 602, "round": 1,
         "power": 2, "neighbours": [{"id": keeper, "margin": 140}], "routes": [], "taken": True},
        {"sender": keeper, "number": 9, "seq": 4, "relay": True, "starting": False,
         "carries_key": True, "sleeps": True, "keeper": leaf, "promise": 600, "round": 0,
         "power": 2, "neighbours": [], "routes": [], "taken": False},
        {"sender": leaf, "number": 10, "seq": 4, "relay": False, "starting": False,
         "carries_key": True, "sleeps": True, "keeper": 0xFFFFFFFF, "promise": 602, "round": 0,
         "power": 2, "neighbours": [], "routes": [], "taken": False},
    ]
    signer = {leaf: 0, keeper: 1}
    for x in announces:
        k = signer[x["sender"]]
        x["seed"] = seeds[k].hex()
        x["frame"] = announce(x, seeds[k]).hex()
        assert announce_taken(bytes.fromhex(x["frame"]), own=other) == x["taken"], x

    sleep = [
        {"wake": w, "content": sleep_content(w).hex(), "valid": sleep_valid(sleep_content(w))}
        for w in (0, 30, 300, 0x8000 | 60, 29, 0x8000 | 61, 0xFFFF)
    ]
    sleep.append({"content": "0400", "valid": False})
    sleep.append({"content": "04012c00", "valid": False})

    hold_cases = [
        {"at_ms": at, "listen": l, "holds": holds(at, l)}
        for at, l in ((0, 2), (1999, 2), (2000, 2), (9000, 10), (10000, 10), (600000, 255))
    ]
    hold_for = [{"wake": w, "hold_for": hold_for_s(w)} for w in (30, 300, 3600, 0x8000 | 60)]
    waits = [
        {"metric": m, "wake": w, "wait_ms": wait_ms(m, w)}
        for m, w in ((70, 30), (420, 300), (0x7FFE, 0x8000 | 60))
    ]

    return {
        "description": "Test vectors for leaves that sleep (draft/sleeping.md). Generated by "
        "vectors/tools/sleeping.py; do not edit by hand.",
        "parameters": {
            "WAKE_MIN": WAKE_MIN_S, "WAKE_MAX": WAKE_MAX_S, "LISTEN_MIN": LISTEN_MIN_S,
            "HOLD_EXTRA": HOLD_EXTRA_S, "ACK_WAIT_ms": ACK_WAIT_MS, "ACK_FACTOR": ACK_FACTOR,
        },
        "routing_ids": {"leaf": leaf, "keeper": keeper, "other": other},
        "polls": polls,
        "poll_answers": answers,
        "held_notices": notices,
        "rejected": rejected,
        "announces": announces,
        "sleep": sleep,
        "holds": hold_cases,
        "hold_for": hold_for,
        "source_waits": waits,
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
