#!/usr/bin/env python3
"""Generates and checks the test vectors for managing a node over the mesh (draft/managing.md).

    python3 vectors/tools/managing.py generate   # rewrite vectors/managing.json
    python3 vectors/tools/managing.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library but companion.py, whose frames, packing and managed
relay it uses: a request is one companion request after its kind, and an answer is companion
frames, each after its length.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion as c  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "managing.json"

KIND_REQUEST, KIND_ANSWER = 0x05, 0x06
REQUEST_MAX, ANSWER_MAX = c.MANAGE_MAX, c.MANAGED_MAX
OWNERS = c.OWNERS
MESH_ANSWER_WAIT_S = 120
TRIAL_S = 900
NOT_OVER_THE_MESH = 13

# What a managed node acts on over the mesh (draft/managing.md#the-connection): every other
# request is answered ERROR 13. SET is acted on for every setting but region (1) and passkey (4).
ALLOWED = {"HELLO", "PING", "SET_TIME", "SYNC", "SET", "SAVE_CONTACT", "REMOVE_CONTACT",
           "END_SESSION", "OWNER", "RESTART"}
SETTINGS_REFUSED = {1, 4}


def request(frame):
    assert 0 < len(frame) <= REQUEST_MAX
    return bytes([KIND_REQUEST]) + frame


def read_request(content):
    """The companion request a request carries, or None if it is to be ignored."""
    if len(content) < 2 or content[0] != KIND_REQUEST or len(content) - 1 > REQUEST_MAX:
        return None
    return content[1:]


def answers(frames):
    return [bytes([KIND_ANSWER]) + packed for packed in c.pack(frames, ANSWER_MAX)]


def read_answer(content):
    """The companion frames an answer carries, or None if it is to be ignored."""
    if not content or content[0] != KIND_ANSWER or len(content) - 1 > ANSWER_MAX:
        return None
    return c.unpack(content[1:])


def allowed(name, setting=None):
    if name == "SET":
        return setting not in SETTINGS_REFUSED
    return name in ALLOWED


def holds(answered_s, confirmed):
    """Whether a SET on trial still holds its new value."""
    return confirmed or answered_s < TRIAL_S


def self_check():
    # A request's content is its kind and then the frame, byte for byte.
    assert request(c.encode("PING", 4)) == b"\x05\x03\x04"
    # An answer packs each frame after its length.
    assert answers([c.encode("OK", 4)]) == [b"\x06\x02\x40\x04"]
    assert read_answer(b"\x06\x02\x40\x04\x03\x41\x05\x0d") == [b"\x40\x04", b"\x41\x05\x0d"]
    # A length that runs past the end, a zero length, and no frame at all are not answers.
    assert read_answer(b"\x06\x05\x40\x04") is None
    assert read_answer(b"\x06\x00") is None
    assert read_answer(b"\x06") is None
    # Frames are never split: a frame that does not fit starts the next answer.
    big = [c.encode("SAVE_CONTACT", i, address=c.BOB, name="x" * 20) for i in range(3)]
    assert [len(a) for a in answers(big)] == [1 + 2 * 56, 1 + 56]
    assert not holds(TRIAL_S, False) and holds(TRIAL_S - 1, False) and holds(10 * TRIAL_S, True)


def build():
    self_check()

    reqs = []
    for why, frame in [
        ("HELLO, at this version", c.encode("HELLO", 1, version=c.VERSION)),
        ("a sync", c.encode("SYNC", 2, after=0)),
        ("a power of 10 dBm", c.encode("SET", 3, setting=3, value=10)),
        ("the PING that ends a trial", c.encode("PING", 4)),
        ("a wake of ten minutes", c.encode("SET", 5, setting=8, value=600)),
        ("making a contact an owner", c.encode("OWNER", 6, address=c.CAROL, owner=1)),
        ("the longest request", c.encode("SAVE_CONTACT", 7, address=c.CAROL, name="")
         + b"\x00" * (REQUEST_MAX - 36)),
        ("a restart", c.encode("RESTART", 8)),
    ]:
        content = request(frame)
        assert read_request(content) == frame
        reqs.append({"why": why, "frame": frame.hex(), "content": content.hex()})

    ans = []
    for why, frames in [
        ("OK", [c.encode("OK", 4)]),
        ("ERROR 13: not over the mesh", [c.encode("ERROR", 5, code=NOT_OVER_THE_MESH)]),
        ("INFO", [c.info()]),
        ("a sync of a relay with three neighbours", c.mast_sync(2)),
    ]:
        contents = answers(frames)
        assert [f for content in contents for f in read_answer(content)] == frames
        ans.append({"why": why, "frames": [f.hex() for f in frames],
                    "contents": [content.hex() for content in contents]})

    rejected = []
    for why, content in [
        ("a request of no frame", b"\x05"),
        ("a request longer than REQUEST_MAX", request(b"\x03\x04")[:1] + b"\x03" * (REQUEST_MAX + 1)),
        ("an answer of no frame", b"\x06"),
        ("an answer whose frame has length 0", b"\x06\x00"),
        ("an answer whose last length runs past its end", b"\x06\x02\x40\x04\x03\x41\x05"),
        ("an answer longer than ANSWER_MAX",
         b"\x06" + b"".join(b"\x02\x40\x04" for _ in range(ANSWER_MAX // 3 + 1))),
    ]:
        assert read_request(content) is None and read_answer(content) is None
        rejected.append({"why": why, "content": content.hex()})

    allowed_cases = []
    for t, (name, _) in sorted(c.FRAMES.items()):
        if not c.REQUESTS[0] <= t <= c.REQUESTS[1]:
            continue
        if name == "SET":
            for setting in sorted(c.SETTINGS):
                allowed_cases.append({"type": name, "setting": setting,
                                      "allowed": allowed(name, setting)})
        else:
            allowed_cases.append({"type": name, "setting": None, "allowed": allowed(name)})

    owners_cases = []
    for owners, sender in [
        ([c.ALICE], c.ALICE),
        ([c.ALICE], c.CAROL),
        ([], c.ALICE),
        ([c.CAROL, c.DAVE, c.ALICE], c.ALICE),
    ]:
        owners_cases.append({"owners": [o.hex() for o in owners], "from": sender.hex(),
                             "answers": sender in owners})

    trials = [{"answered_s": s, "confirmed": confirmed,
               "holds": "new" if holds(s, confirmed) else "old"}
              for s, confirmed in [(0, False), (TRIAL_S - 1, False), (TRIAL_S, False),
                                   (3600, False), (60, True), (3600, True)]]

    syncs = []
    for neighbours in (c.MAST_NEIGHBOURS,
                       [dict(routing_id=0x0A000000 + i, role=i % 2, snr_quarter_db=-20 - i,
                             heard=i) for i in range(20)]):
        frames = c.mast_sync(2, neighbours)
        syncs.append({"self": {k: (v.hex() if isinstance(v, bytes) else v)
                               for k, v in c.MAST_SELF.items()},
                      "owner": c.ALICE.hex(),
                      "neighbours": neighbours,
                      "request": c.encode("SYNC", 2, after=0).hex(),
                      "answers": [a.hex() for a in answers(frames)]})

    return {
        "description": "Managing a node over the mesh (draft/managing.md). A request is the "
        "content of a message for the node, its kind and one companion request; an answer is its "
        "kind and companion frames, each after a u8 length, packed in order into as few answers "
        "as fit. Companion frames are as vectors/companion.json has them, at version "
        f"{c.VERSION}. Syncs are of a relay whose one contact is its owner, the first address, "
        "with no satellite receiver, awake: with three neighbours, and with twenty. Addresses "
        "are those of vectors/companion.json.",
        "generator": "vectors/tools/managing.py",
        "parameters": {"OWNERS": OWNERS, "REQUEST_MAX": REQUEST_MAX, "ANSWER_MAX": ANSWER_MAX,
                       "MESH_ANSWER_WAIT": MESH_ANSWER_WAIT_S, "TRIAL": TRIAL_S},
        "requests": reqs,
        "answers": ans,
        "rejected": rejected,
        "allowed": allowed_cases,
        "owners": owners_cases,
        "trials": trials,
        "syncs": syncs,
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
