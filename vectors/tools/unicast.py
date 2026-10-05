#!/usr/bin/env python3
"""Generates and checks the secured unicast test vectors (draft/unicast-security.md).

    python3 vectors/tools/unicast.py generate   # rewrite vectors/unicast-security.json
    python3 vectors/tools/unicast.py check      # fail if the file differs from what this computes

Needs the `cryptography` package. Before computing anything, it checks its primitives against
published vectors: HKDF-Expand against RFC 5869, and AES-128-CCM with an 8-byte tag against
RFC 3610, which uses exactly the parameters Tern does.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

OUT = Path(__file__).resolve().parent.parent / "unicast-security.json"

FORMAT_V0 = 0b01
TYPE_UNICAST = 0b001
HDR = (FORMAT_V0 << 6) | (TYPE_UNICAST << 3)  # 0x48
TAG_LEN = 8
EPOCH_SHIFT = 5  # 32 messages per epoch
MAX_FRAME = 255
OVERHEAD = 16

INITIATOR_TO_RESPONDER = 0x01
RESPONDER_TO_INITIATOR = 0x02


def expand(prk: bytes, info: bytes, length: int) -> bytes:
    return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=info).derive(prk)


def u32be(n: int) -> bytes:
    return n.to_bytes(4, "big")


def epoch_key(s: bytes, d: int, e: int) -> bytes:
    k = expand(s, b"tern v0 epoch" + bytes([d]), 32)
    for _ in range(e):
        k = expand(k, b"tern v0 next", 32)
    return k


def tag_key(s: bytes, d: int) -> bytes:
    return expand(s, b"tern v0 tag" + bytes([d]), 16)


def iv(s: bytes, d: int) -> bytes:
    return expand(s, b"tern v0 iv" + bytes([d]), 13)


def message_key(s: bytes, d: int, n: int) -> bytes:
    return expand(epoch_key(s, d, n >> EPOCH_SHIFT), b"tern v0 msg" + u32be(n), 16)


def dtag(s: bytes, d: int, n: int) -> bytes:
    enc = Cipher(algorithms.AES(tag_key(s, d)), modes.ECB()).encryptor()
    return (enc.update(bytes(12) + u32be(n)) + enc.finalize())[:4]


def nonce(s: bytes, d: int, n: int) -> bytes:
    return bytes(a ^ b for a, b in zip(iv(s, d), bytes(9) + u32be(n)))


def seal(s: bytes, d: int, n: int, hop: int, label: int, plaintext: bytes) -> bytes:
    assert 0 <= n < 2**32 and len(plaintext) <= MAX_FRAME - OVERHEAD
    t = dtag(s, d, n)
    aad = bytes([HDR]) + t
    ct = AESCCM(message_key(s, d, n), tag_length=TAG_LEN).encrypt(nonce(s, d, n), plaintext, aad)
    return bytes([HDR, hop]) + label.to_bytes(2, "big") + t + ct


def open_frame(s: bytes, d: int, n: int, frame: bytes):
    """The receiver's check for one candidate counter: the plaintext, or None if it fails."""
    if len(frame) < OVERHEAD or frame[0] != HDR or frame[4:8] != dtag(s, d, n):
        return None
    try:
        return AESCCM(message_key(s, d, n), tag_length=TAG_LEN).decrypt(
            nonce(s, d, n), frame[8:], frame[0:1] + frame[4:8]
        )
    except Exception:
        return None


class Receiver:
    """The receiving procedure for one direction of one session: the window and replay rules."""

    def __init__(self, s: bytes, d: int):
        self.s, self.d = s, d
        self.high = None  # H: the highest counter accepted, none to begin with
        self.accepted = set()

    def window(self):
        lo, hi = (0, 31) if self.high is None else (max(0, self.high - 31), self.high + 32)
        return [n for n in range(lo, min(hi, 2**32 - 1) + 1) if n not in self.accepted]

    def matches(self, frame: bytes):
        return [n for n in self.window() if frame[4:8] == dtag(self.s, self.d, n)]

    def accept(self, n: int) -> None:
        self.accepted.add(n)
        if self.high is None or n > self.high:
            self.high = n

    def receive(self, frame: bytes):
        """(counter, plaintext) if the frame is accepted, else None."""
        got = receive_any([self], frame)
        return got and got[1:]


def receive_any(receivers, frame: bytes):
    """One table over several sessions: try every entry whose tag matches, in table order.
    (index of the receiver, counter, plaintext) if the frame is accepted, else None."""
    if len(frame) < OVERHEAD or frame[0] != HDR:
        return None
    for i, rx in enumerate(receivers):
        for n in rx.matches(frame):
            p = open_frame(rx.s, rx.d, n, frame)
            if p is not None:
                rx.accept(n)
                return i, n, p
    return None


# Two sessions whose destination tags collide: session COLLIDE[0] at counter 0 and session
# COLLIDE[1] at counter 29 in direction 1 have the same four bytes. Found by searching the
# secrets SHA-256("tern collision" || u32be(i)) for i from 0, all counters 0 to 31.
COLLIDE = ((1959, 0), (2019, 29))


def collision_secret(i: int) -> bytes:
    return hashlib.sha256(b"tern collision" + u32be(i)).digest()


def self_test() -> None:
    # RFC 5869, test case 1: PRK and OKM.
    prk = bytes.fromhex("077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    )
    assert expand(prk, info, 42) == okm, "HKDF-Expand does not match RFC 5869"

    # RFC 3610, packet vector #1: AES-128, M = 8 (tag), L = 2, 13-byte nonce, 8 bytes of AAD.
    key = bytes.fromhex("c0c1c2c3c4c5c6c7c8c9cacbcccdcecf")
    n = bytes.fromhex("00000003020100a0a1a2a3a4a5")
    packet = bytes(range(0x1F))
    out = bytes.fromhex(
        "588c979a61c663d2f066d0c2c0f989806d5f6b61dac38417e8d12cfdf926e0"
    )
    assert AESCCM(key, tag_length=8).encrypt(n, packet[8:], packet[:8]) == out, (
        "AES-CCM does not match RFC 3610"
    )


def case(name, note, s, d, n, hop, label, plaintext):
    frame = seal(s, d, n, hop, label, plaintext)
    assert open_frame(s, d, n, frame) == plaintext
    return {
        "name": name,
        "note": note,
        "session_secret": s.hex(),
        "direction": d,
        "counter": n,
        "hop": hop,
        "label": label,
        "plaintext": plaintext.hex(),
        "intermediate": {
            "epoch": n >> EPOCH_SHIFT,
            "epoch_key": epoch_key(s, d, n >> EPOCH_SHIFT).hex(),
            "message_key": message_key(s, d, n).hex(),
            "tag_key": tag_key(s, d).hex(),
            "iv": iv(s, d).hex(),
            "nonce": nonce(s, d, n).hex(),
            "dtag": dtag(s, d, n).hex(),
        },
        "frame": frame.hex(),
    }


def build() -> dict:
    s1 = bytes(range(32))
    s2 = bytes.fromhex("a3" * 32)
    hello = "hello".encode()
    greek = "Καλημέρα".encode()  # 16 bytes of UTF-8 for 8 characters
    accepted = [
        case("first", "counter 0, initiator to responder", s1, 1, 0, 0, 0, hello),
        case("reply", "same session, the other direction", s1, 2, 0, 0, 0, hello),
        case("last-of-epoch-0", "counter 31: still epoch 0", s1, 1, 31, 0, 0, hello),
        case("first-of-epoch-1", "counter 32: epoch 1, one step of the epoch chain", s1, 1, 32, 0, 0, hello),
        case("far", "counter 1000: epoch 31", s1, 1, 1000, 0, 0, hello),
        case("relayed", "hop and label set by relays; not authenticated", s1, 1, 0, 3, 0xBEEF, hello),
        case("empty", "no plaintext: the 16-byte minimum frame", s1, 1, 7, 0, 0, b""),
        case("non-latin", "UTF-8 text outside Latin script", s2, 1, 5, 0, 0, greek),
        case("largest", "239 bytes of plaintext: a 255-byte frame", s2, 2, 2, 0, 0, bytes(i & 0xFF for i in range(239))),
    ]

    base = accepted[0]
    frame = bytes.fromhex(base["frame"])
    rejected = []

    def reject(name, note, f):
        assert open_frame(s1, 1, 0, f) is None
        rejected.append({
            "name": name,
            "note": note,
            "session_secret": base["session_secret"],
            "direction": 1,
            "counter": 0,
            "frame": f.hex(),
        })

    flipped = bytearray(frame)
    flipped[-1] ^= 0x01
    reject("tag-flipped", "last bit of the AEAD tag changed", bytes(flipped))
    flipped = bytearray(frame)
    flipped[8] ^= 0x80
    reject("ciphertext-flipped", "first ciphertext bit changed", bytes(flipped))
    reject("header-changed", "a reserved flag set: the header is authenticated", bytes([HDR | 1]) + frame[1:])
    reject("truncated", "15 bytes: shorter than any frame", frame[:15])
    wrong_dir = bytes.fromhex(accepted[1]["frame"])
    reject("wrong-direction", "the responder's counter-0 frame, checked as the initiator's", wrong_dir)

    def sequence(name, note, counters):
        rx = Receiver(s1, 1)
        deliveries = []
        for n in counters:
            p = f"message {n}".encode()
            f = seal(s1, 1, n, 0, 0, p)
            got = rx.receive(f)
            deliveries.append({
                "frame": f.hex(),
                "accept": got is not None,
                "counter": n if got else None,
                "plaintext": p.hex() if got else None,
            })
        return {
            "name": name,
            "note": note,
            "session_secret": s1.hex(),
            "direction": 1,
            "deliveries": deliveries,
        }

    sequences = [
        sequence("replay", "the same frame twice: the second is a replay", [0, 0]),
        sequence("replay-later", "a frame replayed after later ones", [0, 1, 2, 1]),
        sequence("reordered", "arriving out of order, all within the window", [2, 0, 1]),
        sequence("first-window", "before anything is accepted the window is 0 to 31", [32, 31]),
        sequence("ahead-edge", "H + 32 is the last counter ahead in the window", [0, 32]),
        sequence("ahead-beyond", "H + 33 is outside it: 32 lost in a row", [0, 33]),
        sequence("behind", "after H = 60, counter 28 has left the window and 29 has not",
                 [0, 30, 60, 28, 29]),
    ]
    expected = {
        "replay": [True, False],
        "replay-later": [True, True, True, False],
        "reordered": [True, True, True],
        "first-window": [False, True],
        "ahead-edge": [True, True],
        "ahead-beyond": [True, False],
        "behind": [True, True, True, False, True],
    }
    for seq in sequences:
        assert [x["accept"] for x in seq["deliveries"]] == expected[seq["name"]], seq["name"]

    # Both sessions are held by one receiver, so their tags share one table, and the frame matches
    # both entries; only one passes the AEAD check. There is one case for each session's frame,
    # each with a new receiver, so a receiver that keeps one entry per tag, or stops at the first
    # failed check, rejects one of the two cases whichever order it tries the entries in.
    (ia, na), (ib, nb) = COLLIDE
    sa, sb = collision_secret(ia), collision_secret(ib)
    assert dtag(sa, 1, na) == dtag(sb, 1, nb)
    sessions = [{"session_secret": sa.hex(), "direction": 1},
                {"session_secret": sb.hex(), "direction": 1}]
    collisions = []
    for which, (sec, n) in enumerate([(sa, na), (sb, nb)]):
        rxs = [Receiver(sa, 1), Receiver(sb, 1)]
        p = f"collision {which}".encode()
        f = seal(sec, 1, n, 0, 0, p)
        assert sum(len(rx.matches(f)) for rx in rxs) == 2
        assert receive_any(rxs, f) == (which, n, p)
        # Tried the other way round, the wrong session's entry comes first and must fail.
        assert receive_any([Receiver(sb, 1), Receiver(sa, 1)], f) == (1 - which, n, p)
        collisions.append({
            "name": f"tag-collision-{which}",
            "note": f"two sessions whose tags collide; the frame is session {which}'s",
            "sessions": sessions,
            "dtag": dtag(sa, 1, na).hex(),
            "deliveries": [{"frame": f.hex(), "accept": True, "session": which, "counter": n,
                            "plaintext": p.hex()}],
        })

    return {
        "description": "Secured unicast frames, draft 0 (draft/unicast-security.md). For each "
        "accepted case, an implementation given session_secret, direction, counter, hop, label "
        "and plaintext MUST produce frame, and given session_secret, direction and frame MUST "
        "recover counter and plaintext. Each rejected case MUST be rejected by a receiver holding "
        "session_secret and expecting counter in direction. For each sequence, a receiver of a new "
        "session given the deliveries in order MUST accept exactly those marked accept, with "
        "that counter and plaintext. For each collision case, a receiver holding every listed "
        "session, all new, given the deliveries in order MUST accept each, attributed to that "
        "session (an index into sessions) and counter, with that plaintext. Values are hex; "
        "label is an integer sent big-endian.",
        "generator": "vectors/tools/unicast.py",
        "accepted": accepted,
        "rejected": rejected,
        "sequences": sequences,
        "collisions": collisions,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    self_test()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    text = render()
    if cmd == "generate":
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT}")
        return 0
    if cmd == "check":
        if OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} differs from what {Path(__file__).name} computes", file=sys.stderr)
            return 1
        print("ok")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
