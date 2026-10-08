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
import struct
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
HDR_ACK = 0x50  # an acknowledgement (draft/forwarding.md)
TAG_LEN = 8
EPOCH_SHIFT = 5  # 32 messages per epoch
MAX_FRAME = 255
HEAD = 11  # hdr, and the ten bytes that are the forwarding layer's
DTAG = HEAD  # where the destination tag is
BODY = DTAG + 4  # where the ciphertext starts
OVERHEAD = BODY + TAG_LEN  # 23
ACK_LEN = BODY + 4
BEHIND = 31  # how far below H the window reaches

# The forwarding layer's part of the head, where a case does not say otherwise: a frame as its
# source sends it, at 14 dBm, to a neighbour and a destination that are not reserved ids.
ROUTE = {"hops": 32, "power": 14, "next": 0x0A0B0C0D, "destination": 0x01020304}

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


def proof(s: bytes, d: int, n: int) -> bytes:
    """What the destination of message n answers with: the tag's block with 0x01 at byte 11."""
    enc = Cipher(algorithms.AES(tag_key(s, d)), modes.ECB()).encryptor()
    return (enc.update(bytes(11) + b"\x01" + u32be(n)) + enc.finalize())[:4]


def head(hdr: int, route: dict) -> bytes:
    return struct.pack(">BBbII", hdr, route["hops"], route["power"], route["next"],
                       route["destination"])


def nonce(s: bytes, d: int, n: int) -> bytes:
    return bytes(a ^ b for a, b in zip(iv(s, d), bytes(9) + u32be(n)))


def seal(s: bytes, d: int, n: int, plaintext: bytes, route: dict = ROUTE) -> bytes:
    assert 0 <= n < 2**32 and len(plaintext) <= MAX_FRAME - OVERHEAD
    t = dtag(s, d, n)
    aad = bytes([HDR]) + t
    ct = AESCCM(message_key(s, d, n), tag_length=TAG_LEN).encrypt(nonce(s, d, n), plaintext, aad)
    return head(HDR, route) + t + ct


def acknowledgement(s: bytes, d: int, n: int, route: dict = ROUTE) -> bytes:
    """The frame that answers message n of direction d. It travels the other way."""
    return head(HDR_ACK, route) + dtag(s, d, n) + proof(s, d, n)


def acknowledges(s: bytes, d: int, n: int, frame: bytes) -> bool:
    """The source's check: whether a frame shows that its message n of direction d arrived."""
    return (
        len(frame) == ACK_LEN
        and frame[0] == HDR_ACK
        and frame[DTAG:BODY] == dtag(s, d, n)
        and frame[BODY:] == proof(s, d, n)
    )


def open_frame(s: bytes, d: int, n: int, frame: bytes):
    """The receiver's check for one candidate counter: the plaintext, or None if it fails."""
    if len(frame) < OVERHEAD or frame[0] != HDR or frame[DTAG:BODY] != dtag(s, d, n):
        return None
    try:
        return AESCCM(message_key(s, d, n), tag_length=TAG_LEN).decrypt(
            nonce(s, d, n), frame[BODY:], frame[0:1] + frame[DTAG:BODY]
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
        return [n for n in self.window() if frame[DTAG:BODY] == dtag(self.s, self.d, n)]

    def copies(self, frame: bytes):
        """The counters already accepted, no more than 31 below H, whose tag a frame carries: the
        messages a copy of which is acknowledged again."""
        if len(frame) < OVERHEAD or frame[0] != HDR:
            return []
        return [n for n in sorted(self.accepted)
                if self.high - n <= BEHIND and frame[DTAG:BODY] == dtag(self.s, self.d, n)]

    def accept(self, n: int) -> None:
        self.accepted.add(n)
        if self.high is None or n > self.high:
            self.high = n

    def receive(self, frame: bytes):
        """(counter, plaintext) if the frame is accepted, else None."""
        got = receive_any([self], frame)
        return got and got[1:]


def answers(receivers, frame: bytes, got):
    """What a receiver holding several sessions sends in answer to a frame, `got` being what
    receive_any() made of it: one acknowledgement for a frame accepted, and for one that is not,
    one for every accepted message it is a copy of."""
    owed = [got[:2]] if got else [(i, n) for i, rx in enumerate(receivers) for n in rx.copies(frame)]
    return [{"session": i, "counter": n, "proof": proof(receivers[i].s, receivers[i].d, n).hex()}
            for i, n in owed]


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


def case(name, note, s, d, n, plaintext, route=ROUTE):
    frame = seal(s, d, n, plaintext, route)
    assert open_frame(s, d, n, frame) == plaintext
    return {
        "name": name,
        "note": note,
        "session_secret": s.hex(),
        "direction": d,
        "counter": n,
        **route,
        "plaintext": plaintext.hex(),
        "intermediate": {
            "epoch": n >> EPOCH_SHIFT,
            "epoch_key": epoch_key(s, d, n >> EPOCH_SHIFT).hex(),
            "message_key": message_key(s, d, n).hex(),
            "tag_key": tag_key(s, d).hex(),
            "iv": iv(s, d).hex(),
            "nonce": nonce(s, d, n).hex(),
            "dtag": dtag(s, d, n).hex(),
            "proof": proof(s, d, n).hex(),
        },
        "frame": frame.hex(),
    }


def build() -> dict:
    s1 = bytes(range(32))
    s2 = bytes.fromhex("a3" * 32)
    hello = "hello".encode()
    greek = "Καλημέρα".encode()  # 16 bytes of UTF-8 for 8 characters
    accepted = [
        case("first", "counter 0, initiator to responder", s1, 1, 0, hello),
        case("reply", "same session, the other direction", s1, 2, 0, hello),
        case("last-of-epoch-0", "counter 31: still epoch 0", s1, 1, 31, hello),
        case("first-of-epoch-1", "counter 32: epoch 1, one step of the epoch chain", s1, 1, 32, hello),
        case("far", "counter 1000: epoch 31", s1, 1, 1000, hello),
        case("relayed", "hops, power and next as a relay three hops on left them; not authenticated",
             s1, 1, 0, hello, {**ROUTE, "hops": 29, "power": -4, "next": 0xBEEF0001}),
        case("empty", "no plaintext: the 23-byte minimum frame", s1, 1, 7, b""),
        case("non-latin", "UTF-8 text outside Latin script", s2, 1, 5, greek),
        case("largest", "232 bytes of plaintext: a 255-byte frame", s2, 2, 2,
             bytes(i & 0xFF for i in range(MAX_FRAME - OVERHEAD))),
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
    flipped[BODY] ^= 0x80
    reject("ciphertext-flipped", "first ciphertext bit changed", bytes(flipped))
    reject("header-changed", "a reserved flag set: the header is authenticated", bytes([HDR | 1]) + frame[1:])
    reject("truncated", "22 bytes: shorter than any frame", frame[: OVERHEAD - 1])
    reject("first-draft-layout", "the tag at offset 4, as this section first had it: 16 bytes",
           frame[:4] + frame[DTAG:])
    wrong_dir = bytes.fromhex(accepted[1]["frame"])
    reject("wrong-direction", "the responder's counter-0 frame, checked as the initiator's", wrong_dir)

    def sequence(name, note, counters):
        rx = Receiver(s1, 1)
        deliveries = []
        for n in counters:
            p = f"message {n}".encode()
            f = seal(s1, 1, n, p)
            got = rx.receive(f)
            # A frame not accepted is acknowledged all the same if it is a copy of one that was,
            # and not too old a one.
            copy = [] if got else rx.copies(f)
            assert copy in ([], [n])
            deliveries.append({
                "frame": f.hex(),
                "accept": got is not None,
                "counter": n if got else None,
                "plaintext": p.hex() if got else None,
                "acknowledge": bool(got or copy),
                "proof": proof(s1, 1, n).hex() if got or copy else None,
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
        sequence("copy-kept", "a copy of counter 0 is acknowledged while H is 31 or less",
                 [0, 31, 0]),
        sequence("copy-forgotten", "and no longer once H is 32", [0, 32, 0]),
    ]
    expected = {
        "replay": [True, False],
        "replay-later": [True, True, True, False],
        "reordered": [True, True, True],
        "first-window": [False, True],
        "ahead-edge": [True, True],
        "ahead-beyond": [True, False],
        "behind": [True, True, True, False, True],
        "copy-kept": [True, True, False],
        "copy-forgotten": [True, True, False],
    }
    acknowledged = {
        "replay": [True, True],
        "replay-later": [True, True, True, True],
        "reordered": [True, True, True],
        "first-window": [False, True],
        "ahead-edge": [True, True],
        "ahead-beyond": [True, False],
        "behind": [True, True, True, False, True],
        "copy-kept": [True, True, True],
        "copy-forgotten": [True, True, False],
    }
    for seq in sequences:
        assert [x["accept"] for x in seq["deliveries"]] == expected[seq["name"]], seq["name"]
        assert [x["acknowledge"] for x in seq["deliveries"]] == acknowledged[seq["name"]], seq["name"]

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
        f = seal(sec, 1, n, p)
        assert sum(len(rx.matches(f)) for rx in rxs) == 2
        got = receive_any(rxs, f)
        assert got == (which, n, p)
        # Tried the other way round, the wrong session's entry comes first and must fail.
        assert receive_any([Receiver(sb, 1), Receiver(sa, 1)], f) == (1 - which, n, p)
        collisions.append({
            "name": f"tag-collision-{which}",
            "note": f"two sessions whose tags collide; the frame is session {which}'s",
            "sessions": sessions,
            "dtag": dtag(sa, 1, na).hex(),
            "deliveries": [{"frame": f.hex(), "accept": True, "session": which, "counter": n,
                            "plaintext": p.hex(), "acknowledge": answers(rxs, f, got)}],
        })

    # Both frames to one receiver, in turn. Accepting the first removes only its own entry, so
    # the other session's entry under the same tag must still be there for the second frame. A
    # receiver that drops the whole tag bucket on a match rejects the second frame.
    rxs = [Receiver(sa, 1), Receiver(sb, 1)]
    deliveries = []
    for which, (sec, n) in enumerate([(sa, na), (sb, nb)]):
        p = f"collision {which}".encode()
        f = seal(sec, 1, n, p)
        got = receive_any(rxs, f)
        assert got == (which, n, p)
        deliveries.append({"frame": f.hex(), "accept": True, "session": which, "counter": n,
                           "plaintext": p.hex(), "acknowledge": answers(rxs, f, got)})
    # Then the first frame again. It is a copy, and by its tag a copy of both messages: nothing
    # says which, so both are acknowledged, each to its own session's other end.
    f = seal(sa, 1, na, b"collision 0")
    assert receive_any(rxs, f) is None
    both = answers(rxs, f, None)
    assert [(a["session"], a["counter"]) for a in both] == [(0, na), (1, nb)]
    assert both[0]["proof"] != both[1]["proof"]
    deliveries.append({"frame": f.hex(), "accept": False, "session": None, "counter": None,
                       "plaintext": None, "acknowledge": both})
    collisions.append({
        "name": "tag-collision-both",
        "note": "both colliding frames to one receiver: the second session's entry must survive "
        "the first acceptance. Then a copy, which is acknowledged for both",
        "sessions": sessions,
        "dtag": dtag(sa, 1, na).hex(),
        "deliveries": deliveries,
    })

    # The sender owns its counter: both ends of one session, each counting from 0 in its own
    # direction. 34 sends from the initiator cross into epoch 1 (counter 32 and 33); the
    # responder's two replies are interleaved and must use counters 0 and 1.
    class Sender:
        def __init__(self, sec):
            self.s, self.next = sec, {INITIATOR_TO_RESPONDER: 0, RESPONDER_TO_INITIATOR: 0}

        def send(self, d, p):
            n = self.next[d]
            self.next[d] = n + 1
            return n, seal(self.s, d, n, p)

    senders = []
    for name, note, sec, plan in [
        ("both-directions", "the two directions count separately from 0", s1,
         [1, 1, 2, 1, 2]),
        ("into-epoch-1", "34 messages from the initiator: counters 0 to 33, across an epoch",
         s2, [1] * 34),
    ]:
        tx, rx = Sender(sec), {1: Receiver(sec, 1), 2: Receiver(sec, 2)}
        sends, used = [], set()
        for k, d in enumerate(plan):
            p = f"send {k}".encode()
            n, f = tx.send(d, p)
            assert (d, n) not in used and rx[d].receive(f) == (n, p)
            used.add((d, n))
            sends.append({"direction": d, "plaintext": p.hex(), "counter": n, "frame": f.hex()})
        senders.append({"name": name, "note": note, "session_secret": sec.hex(), "sends": sends})

    # Acknowledgements, as the source of the message checks them. The first is the one its
    # destination sends; the rest are what a node on the way, holding no key, might try.
    back = {"hops": 32, "power": 2, "next": 0x0A0B0C0D, "destination": 0x05060708}
    acknowledgements = []

    def ack(name, note, d, n, f, valid):
        assert acknowledges(s1, d, n, f) == valid, name
        acknowledgements.append({
            "name": name,
            "note": note,
            "session_secret": s1.hex(),
            "direction": d,
            "counter": n,
            "dtag": dtag(s1, d, n).hex(),
            "proof": proof(s1, d, n).hex(),
            "frame": f.hex(),
            "valid": valid,
        })

    good = acknowledgement(s1, 1, 0, back)
    ack("first", "the destination's answer to counter 0, initiator to responder", 1, 0, good, True)
    ack("relayed", "the same, some hops on: the head is not checked here", 1, 0,
        acknowledgement(s1, 1, 0, {**back, "hops": 30, "power": -9, "next": 0xBEEF0001}), True)
    ack("epoch-1", "counter 32: the proof needs no epoch key", 1, 32,
        acknowledgement(s1, 1, 32, back), True)
    ack("reply", "the responder's counter 0, answered by the initiator", 2, 0,
        acknowledgement(s1, 2, 0, back), True)
    flipped = bytearray(good)
    flipped[-1] ^= 0x01
    ack("proof-flipped", "last bit of the proof changed", 1, 0, bytes(flipped), False)
    ack("tag-for-proof", "the message's tag sent back as its proof: all a node on the way has",
        1, 0, good[:BODY] + good[DTAG:BODY], False)
    ack("another-counter", "counter 0's tag with counter 1's proof", 1, 0,
        good[:BODY] + proof(s1, 1, 1), False)
    ack("another-direction", "counter 0's tag with the other direction's proof", 1, 0,
        good[:BODY] + proof(s1, 2, 0), False)
    ack("another-message", "the acknowledgement of counter 1, checked against counter 0", 1, 0,
        acknowledgement(s1, 1, 1, back), False)
    ack("too-long", "a byte more than an acknowledgement has", 1, 0, good + b"\x00", False)
    ack("too-short", "a byte fewer", 1, 0, good[:-1], False)
    ack("a-message", "a message's header on it", 1, 0, bytes([HDR]) + good[1:], False)

    return {
        "description": "Secured unicast frames, draft 0 (draft/unicast-security.md), and their "
        "acknowledgements (draft/forwarding.md). For each accepted case, an implementation given "
        "session_secret, direction, counter, hops, power, next, destination and plaintext MUST "
        "produce frame, and given session_secret, direction and frame MUST recover counter and "
        "plaintext. Each rejected case MUST be rejected by a receiver holding session_secret and "
        "expecting counter in direction. For each sequence, a receiver of a new session given the "
        "deliveries in order MUST accept exactly those marked accept, with that counter and "
        "plaintext, and MUST acknowledge exactly those marked acknowledge, with the frame's tag "
        "and that proof. For each collision case, a receiver holding every listed session, all "
        "new, given the deliveries in order MUST accept exactly those marked accept, attributed "
        "to that session (an index into sessions) and counter, with that plaintext, and for each "
        "delivery MUST send exactly the acknowledgements listed, each with the frame's tag and "
        "that proof, to the other end of that session. For each senders case, an "
        "implementation acting as both ends of a new session, given each send's direction and "
        "plaintext in order and choosing the counter itself, MUST produce that send's frame; "
        "counter is given only to help debugging. For each acknowledgements case, the node that "
        "sent message counter in direction, holding session_secret, MUST take frame as showing "
        "that the message arrived if valid is true, and MUST NOT if it is false. Values are hex; "
        "hops, power, next and destination are integers, power signed, laid out as "
        "draft/forwarding.md gives, and where a case does not give them they are 32, 14, "
        "0x0A0B0C0D and 0x01020304.",
        "generator": "vectors/tools/unicast.py",
        "accepted": accepted,
        "rejected": rejected,
        "sequences": sequences,
        "collisions": collisions,
        "senders": senders,
        "acknowledgements": acknowledgements,
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
