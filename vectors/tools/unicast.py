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
HDR_NODE = HDR | 0x01  # the node flag: the plaintext is for the node, not its user
HDRS = (HDR, HDR_NODE)
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
AHEAD = 32  # and how far above

# draft/forwarding.md's: how many acknowledgements of one message a destination sends, the first
# among them, and for how long after it accepted the message it answers copies of it.
COPY_ACKS = 4
COPY_TIME = 600

# draft/unicast-security.md's: when a sender starts a session again, and how long a session lives.
RESTART_AFTER = 2
SESSION_LIFE = 7 * 86400
SESSION_GRACE = 86400

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


def tag_key(s: bytes, d: int, e: int) -> bytes:
    """TK_d(e): each epoch's own, from its epoch key, and erased with it."""
    return expand(epoch_key(s, d, e), b"tern v0 tag", 16)


def first_draft_tag_key(s: bytes, d: int) -> bytes:
    """The one tag key a direction had as first drafted. Only for the cases that it fails."""
    return expand(s, b"tern v0 tag" + bytes([d]), 16)


def iv(s: bytes, d: int) -> bytes:
    return expand(s, b"tern v0 iv" + bytes([d]), 13)


def message_key(s: bytes, d: int, n: int) -> bytes:
    return expand(epoch_key(s, d, n >> EPOCH_SHIFT), b"tern v0 msg" + u32be(n), 16)


def block(key: bytes, b: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(b) + enc.finalize()


def dtag(s: bytes, d: int, n: int) -> bytes:
    return block(tag_key(s, d, n >> EPOCH_SHIFT), bytes(12) + u32be(n))[:4]


def proof(s: bytes, d: int, n: int) -> bytes:
    """What the destination of message n answers with: the tag's block with 0x01 at byte 11."""
    return block(tag_key(s, d, n >> EPOCH_SHIFT), bytes(11) + b"\x01" + u32be(n))[:4]


def head(hdr: int, route: dict) -> bytes:
    return struct.pack(">BBbII", hdr, route["hops"], route["power"], route["next"],
                       route["destination"])


def nonce(s: bytes, d: int, n: int) -> bytes:
    return bytes(a ^ b for a, b in zip(iv(s, d), bytes(9) + u32be(n)))


def seal(s: bytes, d: int, n: int, plaintext: bytes, route: dict = ROUTE, hdr: int = HDR,
         tag: bytes = None) -> bytes:
    """Message n. `tag` replaces its destination tag, for the cases that need a wrong one."""
    assert 0 <= n < 2**32 and len(plaintext) <= MAX_FRAME - OVERHEAD and hdr in HDRS
    t = tag or dtag(s, d, n)
    aad = bytes([hdr]) + t
    ct = AESCCM(message_key(s, d, n), tag_length=TAG_LEN).encrypt(nonce(s, d, n), plaintext, aad)
    return head(hdr, route) + t + ct


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
    if len(frame) < OVERHEAD or frame[0] not in HDRS or frame[DTAG:BODY] != dtag(s, d, n):
        return None
    try:
        return AESCCM(message_key(s, d, n), tag_length=TAG_LEN).decrypt(
            nonce(s, d, n), frame[BODY:], frame[0:1] + frame[DTAG:BODY]
        )
    except Exception:
        return None


class Receiver:
    """The receiving procedure for one direction of one session: the window and replay rules, and
    what it keeps of each message it accepts to answer copies of it (draft/forwarding.md)."""

    def __init__(self, s: bytes, d: int):
        self.s, self.d = s, d
        self.high = None  # H: the highest counter accepted, none to begin with
        self.accepted = set()
        # Counter -> what a copy of it must match, when it was accepted, and how many
        # acknowledgements of it have gone. Not stored: a restart loses it.
        self.kept = {}

    def window(self):
        lo, hi = (0, 31) if self.high is None else (max(0, self.high - BEHIND), self.high + AHEAD)
        return [n for n in range(lo, min(hi, 2**32 - 1) + 1) if n not in self.accepted]

    def matches(self, frame: bytes):
        return [n for n in self.window() if frame[DTAG:BODY] == dtag(self.s, self.d, n)]

    def copies(self, frame: bytes, at: int):
        """The counters a frame is a copy of, and still answered for: accepted, no more than 31
        below H, the frame of the same length and hdr with the same destination tag and first four
        bytes of AEAD tag, fewer than COPY_ACKS acknowledgements sent, and no more than COPY_TIME
        since it was accepted."""
        if len(frame) < OVERHEAD or frame[0] not in HDRS:
            return []
        out = []
        for n in sorted(self.accepted):
            k = self.kept.get(n)
            if (k and self.high - n <= BEHIND and k["match"] == match(frame)
                    and k["acks"] < COPY_ACKS and at - k["at"] <= COPY_TIME):
                out.append(n)
        return out

    def accept(self, n: int, frame: bytes, at: int) -> None:
        self.accepted.add(n)
        self.kept[n] = {"match": match(frame), "at": at, "acks": 0}
        if self.high is None or n > self.high:
            self.high = n

    def restart(self) -> None:
        """What a restart leaves: H and which counters were accepted, which it stored."""
        self.kept = {}

    def receive(self, frame: bytes, at: int = 0):
        """(counter, plaintext) if the frame is accepted, else None."""
        got = receive_any([self], frame, at)
        return got and got[1:]


def match(frame: bytes):
    """What a copy shares with its message: its length, hdr, tag and first four bytes of AEAD tag."""
    return (len(frame), frame[0], frame[DTAG:BODY], frame[-TAG_LEN:][:4])


def answers(receivers, frame: bytes, got, at: int):
    """What a receiver holding several sessions sends in answer to a frame, `got` being what
    receive_any() made of it: one acknowledgement for a frame accepted, and for one that is not,
    one for every accepted message it is a copy of and still answers."""
    owed = [got[:2]] if got else [(i, n) for i, rx in enumerate(receivers)
                                  for n in rx.copies(frame, at)]
    for i, n in owed:
        receivers[i].kept[n]["acks"] += 1
    return [{"session": i, "counter": n, "proof": proof(receivers[i].s, receivers[i].d, n).hex()}
            for i, n in owed]


def receive_any(receivers, frame: bytes, at: int = 0):
    """One table over several sessions: try every entry whose tag matches, in table order.
    (index of the receiver, counter, plaintext) if the frame is accepted, else None."""
    if len(frame) < OVERHEAD or frame[0] not in HDRS:
        return None
    for i, rx in enumerate(receivers):
        for n in rx.matches(frame):
            p = open_frame(rx.s, rx.d, n, frame)
            if p is not None:
                rx.accept(n, frame, at)
                return i, n, p
    return None


class Sender:
    """Both ends' senders of one session: each direction's counter, and K and G, which say when a
    sender starts again (draft/unicast-security.md, "Starting again"). All three are stored."""

    def __init__(self, s: bytes):
        self.s = s
        self.next = {INITIATOR_TO_RESPONDER: 0, RESPONDER_TO_INITIATOR: 0}
        self.k = {INITIATOR_TO_RESPONDER: None, RESPONDER_TO_INITIATOR: None}
        self.g = {INITIATOR_TO_RESPONDER: 0, RESPONDER_TO_INITIATOR: 0}

    def may_send(self, d: int) -> bool:
        n, k = self.next[d], self.k[d]
        return n <= (31 if k is None else k + 32) and self.g[d] < RESTART_AFTER

    def send(self, d: int, p: bytes):
        """(counter, frame), or None where the sender starts again instead."""
        if not self.may_send(d):
            return None
        n = self.next[d]
        self.next[d] = n + 1
        return n, seal(self.s, d, n, p)

    def then(self, d: int, n: int, what: str) -> None:
        if what == "acknowledged":
            self.k[d] = n if self.k[d] is None else max(self.k[d], n)
            self.g[d] = 0
        elif what == "given up":
            self.g[d] += 1


# Two sessions whose destination tags collide: session COLLIDE[0] at counter 17 and session
# COLLIDE[1] at counter 29 in direction 1 have the same four bytes. Found by searching the
# secrets SHA-256("tern collision" || u32be(i)) for i from 0, all counters 0 to 31, for the first
# tag two secrets share.
COLLIDE = ((72, 17), (4609, 29))


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


def case(name, note, s, d, n, plaintext, route=ROUTE, hdr=HDR):
    frame = seal(s, d, n, plaintext, route, hdr)
    assert open_frame(s, d, n, frame) == plaintext
    return {
        "name": name,
        "note": note,
        "session_secret": s.hex(),
        "direction": d,
        "counter": n,
        "hdr": hdr,
        **route,
        "plaintext": plaintext.hex(),
        "intermediate": {
            "epoch": n >> EPOCH_SHIFT,
            "epoch_key": epoch_key(s, d, n >> EPOCH_SHIFT).hex(),
            "message_key": message_key(s, d, n).hex(),
            "tag_key": tag_key(s, d, n >> EPOCH_SHIFT).hex(),
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
        case("first-of-epoch-1", "counter 32: epoch 1, one step of the epoch chain, and epoch 1's "
             "tag key", s1, 1, 32, hello),
        case("far", "counter 1000: epoch 31", s1, 1, 1000, hello),
        case("relayed", "hops, power and next as a relay three hops on left them; not authenticated",
             s1, 1, 0, hello, {**ROUTE, "hops": 29, "power": -4, "next": 0xBEEF0001}),
        case("empty", "no plaintext: the 23-byte minimum frame", s1, 1, 7, b""),
        case("non-latin", "UTF-8 text outside Latin script", s2, 1, 5, greek),
        case("largest", "232 bytes of plaintext: a 255-byte frame", s2, 2, 2,
             bytes(i & 0xFF for i in range(MAX_FRAME - OVERHEAD))),
        case("for-the-node", "the node flag set: the plaintext is a group's invite (draft/groups.md), "
             "and the counter is the session's like any other", s1, 1, 1,
             bytes([0x01]) + bytes.fromhex("c4" * 16) + b"hut", hdr=HDR_NODE),
    ]
    assert tag_key(s1, 1, 0) != tag_key(s1, 1, 1)

    base = accepted[0]
    frame = bytes.fromhex(base["frame"])
    rejected = []

    def reject(name, note, f, n=0):
        assert open_frame(s1, 1, n, f) is None
        rejected.append({
            "name": name,
            "note": note,
            "session_secret": base["session_secret"],
            "direction": 1,
            "counter": n,
            "frame": f.hex(),
        })

    flipped = bytearray(frame)
    flipped[-1] ^= 0x01
    reject("tag-flipped", "last bit of the AEAD tag changed", bytes(flipped))
    flipped = bytearray(frame)
    flipped[BODY] ^= 0x80
    reject("ciphertext-flipped", "first ciphertext bit changed", bytes(flipped))
    reject("header-changed", "the node flag set on a frame sealed without it: the header is authenticated",
           bytes([HDR_NODE]) + frame[1:])
    reject("reserved-flag", "a reserved flag set", bytes([HDR | 2]) + frame[1:])
    reject("truncated", "22 bytes: shorter than any frame", frame[: OVERHEAD - 1])
    reject("first-draft-layout", "the tag at offset 4, as this section first had it: 16 bytes",
           frame[:4] + frame[DTAG:])
    wrong_dir = bytes.fromhex(accepted[1]["frame"])
    reject("wrong-direction", "the responder's counter-0 frame, checked as the initiator's", wrong_dir)
    for n in (0, 32):
        old = block(first_draft_tag_key(s1, 1), bytes(12) + u32be(n))[:4]
        assert old != dtag(s1, 1, n)
        reject(f"first-draft-tag-key-{n}", f"counter {n} sealed whole, but with the destination "
               "tag the first draft's one tag key gives", seal(s1, 1, n, hello, tag=old), n)

    def sequence(name, note, steps):
        """Each step is a counter, sealed as that message; ("forged", n, len) for a frame with
        message n's tag and hdr that is not message n, of len bytes of plaintext; or "restart".
        Deliveries are a second apart unless a step gives ("at", seconds, step)."""
        rx = Receiver(s1, 1)
        deliveries = []
        at, restart = 0, False
        for step in steps:
            if step == "restart":
                rx.restart()
                restart = True
                continue
            if isinstance(step, tuple) and step[0] == "at":
                at, step = step[1], step[2]
            if isinstance(step, tuple) and step[0] == "forged":
                _, n, ln = step
                p = bytes([0x66]) * ln
                f = seal(s1, 1, n, p, tag=dtag(s1, 1, n))
                f = f[:BODY] + bytes(x ^ 0x5A for x in f[BODY:])  # another ciphertext and check
                n = None
            else:
                n = step
                p = f"message {n}".encode()
                f = seal(s1, 1, n, p)
            got = rx.receive(f, at)
            # A frame not accepted is acknowledged all the same if it is a copy of one that was,
            # and not too old a one, nor answered too often.
            ack = answers([rx], f, (0, *got) if got else None, at)
            assert len(ack) <= 1
            d = {
                "frame": f.hex(),
                "at_s": at,
                "accept": got is not None,
                "counter": got[0] if got else None,
                "plaintext": p.hex() if got else None,
                "acknowledge": bool(ack),
                "proof": ack[0]["proof"] if ack else None,
            }
            if restart:
                d = {"restart": True, **d}
            deliveries.append(d)
            at, restart = at + 1, False
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
        sequence("copy-capped", "COPY_ACKS acknowledgements of one message, the first among them, "
                 "and no more", [0, 0, 0, 0, 0]),
        sequence("copy-late", "a copy is answered COPY_TIME after its message was accepted, and "
                 "not a second later", [0, ("at", COPY_TIME, 0), ("at", COPY_TIME + 1, 0)]),
        sequence("copy-forged", "frames with counter 1's tag and hdr that are not it, of its "
                 "length and of another: neither is a copy, and neither is answered",
                 [1, ("forged", 1, len(b"message 1")), ("forged", 1, 3), 1]),
        sequence("restart", "the window outlives a restart: a counter accepted before is not "
                 "accepted again, and one not yet accepted still is. The replays come after "
                 "COPY_TIME, so that whether a copy is answered does not depend on what a restart "
                 "kept", [0, 2, "restart", 1, "restart", ("at", 700, 2), 0, 3]),
        sequence("restart-ahead", "H outlives a restart: after H = 32, counter 64 is in the "
                 "window and 65 is not", [0, 32, "restart", 65, 64]),
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
        "copy-capped": [True, False, False, False, False],
        "copy-late": [True, False, False],
        "copy-forged": [True, False, False, False],
        "restart": [True, True, True, False, False, True],
        "restart-ahead": [True, True, False, True],
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
        "copy-capped": [True, True, True, True, False],
        "copy-late": [True, True, False],
        "copy-forged": [True, False, False, True],
        "restart": [True, True, True, False, False, True],
        "restart-ahead": [True, True, False, True],
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
            "deliveries": [{"frame": f.hex(), "at_s": 0, "accept": True, "session": which,
                            "counter": n, "plaintext": p.hex(),
                            "acknowledge": answers(rxs, f, got, 0)}],
        })

    # Both frames to one receiver, in turn. Accepting the first removes only its own entry, so
    # the other session's entry under the same tag must still be there for the second frame. A
    # receiver that drops the whole tag bucket on a match rejects the second frame.
    rxs = [Receiver(sa, 1), Receiver(sb, 1)]
    deliveries = []
    for which, (sec, n) in enumerate([(sa, na), (sb, nb)]):
        p = f"collision {which}".encode()
        f = seal(sec, 1, n, p)
        got = receive_any(rxs, f, which)
        assert got == (which, n, p)
        deliveries.append({"frame": f.hex(), "at_s": which, "accept": True, "session": which,
                           "counter": n, "plaintext": p.hex(),
                           "acknowledge": answers(rxs, f, got, which)})
    # Then each frame again. Each is a copy by its tag of both messages, but by its AEAD tag of
    # its own only: a receiver that knows a copy by its tag alone acknowledges both.
    for which, (sec, n) in enumerate([(sa, na), (sb, nb)]):
        f = seal(sec, 1, n, f"collision {which}".encode())
        assert receive_any(rxs, f, 2 + which) is None
        one = answers(rxs, f, None, 2 + which)
        assert [(a["session"], a["counter"]) for a in one] == [(which, n)]
        deliveries.append({"frame": f.hex(), "at_s": 2 + which, "accept": False, "session": None,
                           "counter": None, "plaintext": None, "acknowledge": one})
    collisions.append({
        "name": "tag-collision-both",
        "note": "both colliding frames to one receiver: the second session's entry must survive "
        "the first acceptance. Then a copy of each, which shares its tag with both messages but "
        "its AEAD tag with its own: it is acknowledged for its own alone",
        "sessions": sessions,
        "dtag": dtag(sa, 1, na).hex(),
        "deliveries": deliveries,
    })

    # The sender owns its counter: both ends of one session, each counting from 0 in its own
    # direction, across restarts, and starting again where the window may not reach or messages
    # are given up.
    senders = []

    def sender_case(name, note, sec, plan):
        """plan: each step is (direction, then) for a send, `then` being what became of it, or
        "restart"."""
        tx = Sender(sec)
        sends, used, restart = [], set(), False
        for k, step in enumerate(plan):
            if step == "restart":
                restart = True
                continue
            d, then = step
            p = f"send {k}".encode()
            got = tx.send(d, p)
            if got is None:
                assert then is None
                sends.append({**({"restart": True} if restart else {}), "direction": d,
                              "plaintext": p.hex(), "counter": None, "frame": None, "then": None})
                restart = False
                continue
            n, f = got
            assert (d, n) not in used and open_frame(sec, d, n, f) == p
            used.add((d, n))
            tx.then(d, n, then)
            sends.append({**({"restart": True} if restart else {}), "direction": d,
                          "plaintext": p.hex(), "counter": n, "frame": f.hex(), "then": then})
            restart = False
        senders.append({"name": name, "note": note, "session_secret": sec.hex(), "sends": sends})
        return sends

    sender_case("both-directions", "the two directions count separately from 0", s1,
                [(1, "acknowledged"), (1, "acknowledged"), (2, "acknowledged"),
                 (1, "acknowledged"), (2, "acknowledged")])
    sender_case("into-epoch-1", "34 messages from the initiator: counters 0 to 33, across an epoch",
                s2, [(1, "acknowledged")] * 34)
    sender_case("restarts", "the counter outlives a restart of both ends: each goes on from the "
                "next", s1, [(1, "acknowledged"), (2, "acknowledged"), (1, "acknowledged"),
                             "restart", (1, "acknowledged"), (2, "acknowledged"), "restart",
                             (1, "acknowledged")])
    out = sender_case("unanswered", "32 messages with nothing acknowledged, and no more: counter "
                      "32 might be beyond the receiver's window", s2, [(1, None)] * 32 + [(1, None)])
    assert out[-1]["frame"] is None and out[-2]["counter"] == 31
    out = sender_case("acknowledged-moves-on", "with counter 5 acknowledged, messages go up to "
                      "37, and no further", s2, [(1, None)] * 5 + [(1, "acknowledged")]
                      + [(1, None)] * 32 + [(1, None)])
    assert out[-1]["frame"] is None and out[-2]["counter"] == 37
    out = sender_case("given-up", "two messages given up in a row: the third starts again", s1,
                      [(1, "acknowledged"), (1, "given up"), (1, "given up"), (1, None)])
    assert out[-1]["frame"] is None
    out = sender_case("given-up-apart", "an acknowledgement between two given up: the next goes",
                      s1, [(1, "given up"), (1, "acknowledged"), (1, "given up"),
                           (1, "acknowledged")])
    assert all(x["frame"] for x in out)
    out = sender_case("given-up-restart", "what is given up outlives a restart", s1,
                      [(2, "given up"), "restart", (2, "given up"), (2, None)])
    assert out[-1]["frame"] is None

    lifetimes = []
    made = 1000
    for at, sends, holds in [
        (made, True, True),
        (made + SESSION_LIFE, True, True),
        (made + SESSION_LIFE + 1, False, True),
        (made + SESSION_LIFE + SESSION_GRACE, False, True),
        (made + SESSION_LIFE + SESSION_GRACE + 1, False, False),
    ]:
        assert sends == (at - made <= SESSION_LIFE)
        assert holds == (at - made <= SESSION_LIFE + SESSION_GRACE)
        lifetimes.append({"made_s": made, "at_s": at, "sends": sends, "holds": holds})

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
    ack("epoch-1", "counter 32: its tag and proof are made with epoch 1's tag key", 1, 32,
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
    old_key = first_draft_tag_key(s1, 1)
    ack("first-draft-tag-key", "counter 32's tag and proof as the first draft's one tag key "
        "made them", 1, 32, head(HDR_ACK, back) + block(old_key, bytes(12) + u32be(32))[:4]
        + block(old_key, bytes(11) + b"\x01" + u32be(32))[:4], False)

    return {
        "description": "Secured unicast frames, draft 0 (draft/unicast-security.md), and their "
        "acknowledgements (draft/forwarding.md). For each accepted case, an implementation given "
        "session_secret, direction, counter, hops, power, next, destination and plaintext MUST "
        "produce frame, and given session_secret, direction and frame MUST recover counter and "
        "plaintext. Each rejected case MUST be rejected by a receiver holding session_secret and "
        "expecting counter in direction. For each sequence, a receiver of a new session given the "
        "deliveries in order, each at at_s seconds, MUST accept exactly those marked accept, with "
        "that counter and plaintext, and MUST acknowledge exactly those marked acknowledge, with "
        "the frame's tag and that proof; a delivery marked restart comes after the receiver has "
        "restarted, keeping only what it stored. For each collision case, a receiver holding "
        "every listed session, all new, given the deliveries in order, each at at_s seconds, MUST "
        "accept exactly those marked accept, attributed to that session (an index into sessions) "
        "and counter, with that plaintext, and for each delivery MUST send exactly the "
        "acknowledgements listed, each with the frame's tag and that proof, to the other end of "
        "that session. For each senders case, an implementation acting as both ends of a new "
        "session, given each send's direction and plaintext in order and choosing the counter "
        "itself, MUST produce that send's frame, or, where frame is null, MUST NOT send in the "
        "session but start again; a send marked restart comes after both ends have restarted, "
        "keeping only what they stored, and then is what became of the message afterwards: "
        "acknowledged (validly), given up, or null for nothing yet. counter is given only to help "
        "debugging. For each lifetimes case, a node that derived a session's secret at made_s "
        "seconds MAY send in it at at_s if sends is true and MUST NOT if it is false, and MUST "
        "have erased it by at_s if holds is false. For each acknowledgements case, the node that "
        "sent message counter in direction, holding session_secret, MUST take frame as showing "
        "that the message arrived if valid is true, and MUST NOT if it is false. Values are hex; "
        "hdr is 72 (0x48), or 73 with the node flag set. hops, power, next and destination are "
        "integers, power signed, laid out as draft/forwarding.md gives, and where a case does not "
        "give them they are 32, 14, 0x0A0B0C0D and 0x01020304.",
        "generator": "vectors/tools/unicast.py",
        "accepted": accepted,
        "rejected": rejected,
        "sequences": sequences,
        "collisions": collisions,
        "senders": senders,
        "lifetimes": lifetimes,
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
