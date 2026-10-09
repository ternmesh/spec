#!/usr/bin/env python3
"""Generates and checks the group test vectors (draft/groups.md).

    python3 vectors/tools/groups.py generate   # rewrite vectors/groups.json
    python3 vectors/tools/groups.py check      # fail if the file differs from what this computes

Needs the `cryptography` package. Its primitives are unicast.py's, beside this file, which checks
them against RFC 5869 and RFC 3610 before anything is computed.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unicast  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "groups.json"

HDR = 0x60  # format 01, type 100, no flags
HDR_NODE = 0x61  # the same, with the node flag set: content is for the node
HDRS = (HDR, HDR_NODE)
KIND_POSITION = 0x02
HEAD = 3
NONCE = HEAD  # where the nonce is
GTAG = NONCE + 8
BODY = GTAG + 4
TAG_LEN = 8
MIN_FRAME = BODY + 4 + TAG_LEN  # 27
MAX_FRAME = 255
RECENT = 64
RESERVED = (0, 0xFFFFFFFF)
KIND_INVITE = 0x01
NAME_MAX = 31
FLOOD = {"hops": 5, "power": 14}


def group_key(g):
    return unicast.expand(g, b"tern v0 group key", 16)


def tag_key(g):
    return unicast.expand(g, b"tern v0 group tag", 16)


def gtag(g, n):
    enc = Cipher(algorithms.AES(tag_key(g)), modes.ECB()).encryptor()
    return (enc.update(bytes(8) + n) + enc.finalize())[:4]


def seal(g, n, sender, content, flood=FLOOD, hdr=HDR):
    assert len(g) == 16 and len(n) == 8 and len(content) <= MAX_FRAME - MIN_FRAME and hdr in HDRS
    t = gtag(g, n)
    plaintext = struct.pack(">I", sender) + content
    ct = AESCCM(group_key(g), tag_length=TAG_LEN).encrypt(bytes(5) + n, plaintext, bytes([hdr]) + n + t)
    return struct.pack(">BBb", hdr, flood["hops"], flood["power"]) + n + t + ct


def matches(g, frame):
    return (MIN_FRAME <= len(frame) <= MAX_FRAME and frame[0] in HDRS
            and frame[GTAG:BODY] == gtag(g, frame[NONCE:GTAG]))


def open_frame(g, me, frame):
    """A member's check, but for the nonces it holds: (from, content), or None. Whether content
    is for the node is frame[0] & 1."""
    if not matches(g, frame):
        return None
    n = frame[NONCE:GTAG]
    try:
        p = AESCCM(group_key(g), tag_length=TAG_LEN).decrypt(
            bytes(5) + n, frame[BODY:], frame[0:1] + n + frame[GTAG:BODY])
    except Exception:
        return None
    sender = struct.unpack(">I", p[:4])[0]
    if sender in RESERVED or sender == me:
        return None
    return sender, p[4:]


class Member:
    """A node and the groups it holds: which frames it accepts, each once."""

    def __init__(self, me, secrets):
        self.me, self.secrets = me, secrets
        self.recent = [[] for _ in secrets]

    def receive(self, frame):
        """(index of the group, from, content) if the frame is accepted, else None."""
        for i, g in enumerate(self.secrets):
            got = open_frame(g, self.me, frame)
            if got is None or frame[NONCE:GTAG] in self.recent[i]:
                continue
            self.recent[i] = (self.recent[i] + [frame[NONCE:GTAG]])[-RECENT:]
            return (i, *got)
        return None


def invite(g, name):
    assert len(g) == 16 and len(name.encode()) <= NAME_MAX
    return bytes([KIND_INVITE]) + g + name.encode()


def read_invite(p):
    """(secret, name) from the plaintext of a message for the node, or None."""
    if not 17 <= len(p) <= 17 + NAME_MAX or p[0] != KIND_INVITE:
        return None
    try:
        return p[1:17], p[17:].decode("utf-8")
    except UnicodeDecodeError:
        return None


def secret(i):
    return hashlib.sha256(b"tern group" + i.to_bytes(4, "big")).digest()[:16]


def colliding():
    """Two groups and a nonce where both give the same tag: the secrets secret(i) for i from 0,
    and the nonce of eight zero bytes. Found by search; 2^16 secrets or so are enough."""
    seen = {}
    for i in range(1 << 20):
        t = gtag(secret(i), bytes(8))
        if t in seen:
            return seen[t], i
        seen[t] = i
    raise AssertionError("no collision found")


# What colliding() finds, kept so that the search runs only in the self-check's place.
COLLIDE = (48640, 56128)


def case(name, note, g, n, sender, content, flood=FLOOD, me=0x0A0B0C0D, hdr=HDR):
    frame = seal(g, n, sender, content, flood, hdr)
    assert open_frame(g, me, frame) == (sender, content)
    return {
        "name": name,
        "note": note,
        "hdr": hdr,
        "node": hdr == HDR_NODE,
        "group_secret": g.hex(),
        "nonce": n.hex(),
        "from": sender,
        "content": content.hex(),
        **flood,
        "self": me,
        "intermediate": {
            "group_key": group_key(g).hex(),
            "tag_key": tag_key(g).hex(),
            "gtag": gtag(g, n).hex(),
            "ccm_nonce": (bytes(5) + n).hex(),
            "associated_data": (bytes([hdr]) + n + gtag(g, n)).hex(),
            "plaintext": (struct.pack(">I", sender) + content).hex(),
        },
        "frame": frame.hex(),
    }


def build():
    unicast.self_test()
    g1 = bytes(range(16))
    g2 = bytes.fromhex("c4" * 16)
    n1 = bytes.fromhex("0001020304050607")
    alice, me = 0x1D2E3F40, 0x0A0B0C0D
    hello = "hello".encode()
    accepted = [
        case("first", "a short message", g1, n1, alice, hello),
        case("another-nonce", "the same words again: nothing in the frame is as before", g1,
             bytes.fromhex("f0e1d2c3b4a59687"), alice, hello),
        case("another-group", "the same nonce under another secret", g2, n1, alice, hello),
        case("passed-on", "hops and power as a relay left them; not authenticated", g1, n1, alice,
             hello, {"hops": 2, "power": -4}),
        case("empty", "no content: the 27-byte minimum frame", g1, bytes.fromhex("1111111111111111"),
             alice, b""),
        case("non-latin", "UTF-8 text outside Latin script", g2, bytes.fromhex("2222222222222222"),
             0xFFFFFFFE, "Καλημέρα".encode()),
        case("largest", "228 bytes of content: a 255-byte frame", g2, bytes.fromhex("3333333333333333"),
             1, bytes(i & 0xFF for i in range(MAX_FRAME - MIN_FRAME))),
        case("for-the-node", "the node flag set: content is for the node, here a position "
             "(draft/positions.md) of a town", g1, bytes.fromhex("4444444444444444"), alice,
             bytes.fromhex("0260" "8a6b80"), hdr=HDR_NODE),
        case("for-the-node-unknown-kind", "the node flag set and a kind no section defines: "
             "accepted, and nothing more done with it", g1, bytes.fromhex("5555555555555555"),
             alice, b"\x7f", hdr=HDR_NODE),
    ]

    frame = bytes.fromhex(accepted[0]["frame"])
    rejected = []

    def reject(name, note, f, who=me, g=g1):
        assert Member(who, [g]).receive(f) is None
        rejected.append({"name": name, "note": note, "group_secret": g.hex(), "self": who,
                         "frame": f.hex()})

    def flip(at, bit=0x01):
        f = bytearray(frame)
        f[at] ^= bit
        return bytes(f)

    reject("check-flipped", "last bit of the AEAD tag changed", flip(-1))
    reject("ciphertext-flipped", "first ciphertext bit changed", flip(BODY, 0x80))
    reject("nonce-flipped", "a bit of the nonce changed: the tag no longer matches it", flip(NONCE))
    other = bytearray(flip(NONCE))
    other[GTAG:BODY] = gtag(g1, bytes(other[NONCE:GTAG]))
    reject("nonce-changed", "another nonce, with the tag that goes with it: the check fails", bytes(other))
    reject("tag-flipped", "a bit of the group tag changed", flip(GTAG))
    reject("node-flag-set", "the node flag set on a frame sealed without it: the header is "
           "authenticated", bytes([HDR_NODE]) + frame[1:])
    node_frame = bytes.fromhex(accepted[-2]["frame"])
    reject("node-flag-cleared", "the node flag cleared on a frame sealed with it",
           bytes([HDR]) + node_frame[1:])
    reject("reserved-flag", "a reserved flag set", bytes([HDR | 2]) + frame[1:])
    odd = HDR | 4
    sealed = AESCCM(group_key(g1), tag_length=TAG_LEN).encrypt(
        bytes(5) + n1, struct.pack(">I", alice) + hello, bytes([odd]) + n1 + gtag(g1, n1))
    reject("reserved-flag-sealed", "a reserved flag set, and sealed with it rightly: not a group "
           "frame of this draft", struct.pack(">BBb", odd, 5, 14) + n1 + gtag(g1, n1) + sealed)
    reject("a-message", "a unicast message's header on it", bytes([0x48]) + frame[1:])
    reject("truncated", "26 bytes: shorter than any frame", frame[:MIN_FRAME - 1])
    reject("another-group", "a frame of a group this node does not hold",
           bytes.fromhex(accepted[2]["frame"]))
    reject("from-nobody", "from is 0x00000000: sealed rightly, and refused", seal(g1, n1, 0, hello))
    reject("from-everyone", "from is 0xFFFFFFFF", seal(g1, n1, 0xFFFFFFFF, hello))
    reject("from-itself", "from is the receiver's own routing id: another member writing as it",
           seal(g1, n1, me, hello))
    short = AESCCM(group_key(g1), tag_length=TAG_LEN).encrypt(
        bytes(5) + n1, b"\x01\x02\x03", bytes([HDR]) + n1 + gtag(g1, n1))
    reject("no-from", "three bytes of plaintext, sealed rightly: 26 bytes",
           struct.pack(">BBb", HDR, 5, 14) + n1 + gtag(g1, n1) + short)

    a, b = COLLIDE
    ga, gb = secret(a), secret(b)
    assert gtag(ga, bytes(8)) == gtag(gb, bytes(8)) and ga != gb
    members = []

    def member(name, note, who, secrets, frames):
        m = Member(who, secrets)
        deliveries = []
        for f in frames:
            got = m.receive(f)
            d = {"frame": f.hex(), "accept": got is not None}
            if got:
                d.update({"group": got[0], "from": got[1], "content": got[2].hex()})
            deliveries.append(d)
        members.append({"name": name, "note": note, "self": who,
                        "groups": [g.hex() for g in secrets], "deliveries": deliveries})
        return deliveries

    f1 = seal(g1, n1, alice, hello)
    f2 = seal(g2, n1, alice, b"two")
    d = member("two-groups", "frames of each group, of neither, and one a second time", me, [g1, g2],
               [f1, f2, seal(secret(7), n1, alice, hello), f1,
                seal(g1, bytes.fromhex("0001020304050608"), alice, hello)])
    assert [x["accept"] for x in d] == [True, True, False, False, True]
    d = member("again-passed-on", "a copy that came another way, hops and power changed: the same frame",
               me, [g1], [f1, seal(g1, n1, alice, hello, {"hops": 1, "power": 3})])
    assert [x["accept"] for x in d] == [True, False]
    d = member("tags-collide", "two groups whose tags for this nonce are the same four bytes: a frame "
               f"of each (the secrets are the first 16 bytes of SHA-256(\"tern group\" || u32be(i)) for i = {a} and {b})",
               me, [ga, gb], [seal(gb, bytes(8), alice, b"second"), seal(ga, bytes(8), alice, b"first")])
    assert [x.get("group") for x in d] == [1, 0]
    words = seal(g1, bytes.fromhex("6666666666666666"), alice, hello)
    for_node = seal(g1, bytes.fromhex("6666666666666666"), alice, b"\x02\x00", hdr=HDR_NODE)
    d = member("node-and-words-one-nonce", "a frame for the node and one of words share a group's "
               "nonces: the second with a nonce the first had is refused, whichever kind it is",
               me, [g1], [for_node, words, seal(g1, bytes.fromhex("6666666666666667"), alice, hello)])
    assert [x["accept"] for x in d] == [True, False, True]
    d = member("same-nonce-two-groups", "a nonce accepted for one group does not stand against another's",
               me, [g1, g2], [f1, f2])
    assert [x["accept"] for x in d] == [True, True]

    def numbered(k):
        return seal(g1, k.to_bytes(8, "big"), alice, hello)

    first, count = 1000, RECENT + 1
    m = Member(me, [g1])
    for k in range(first, first + count):
        assert m.receive(numbered(k)) is not None
    again = []
    for k in (first + count - 1, first + 1, first, first + 1):
        again.append({"nonce": k.to_bytes(8, "big").hex(), "frame": numbered(k).hex(),
                      "accept": m.receive(numbered(k)) is not None})
    assert [x["accept"] for x in again] == [False, False, True, True]
    recent = [{
        "name": "edge",
        "note": "65 frames accepted: the first's nonce has been dropped and the second's has not. "
        "Accepting the first again drops the second's.",
        "group_secret": g1.hex(), "self": me, "from": alice, "content": hello.hex(),
        **FLOOD, "first": first, "count": count, "again": again,
    }]

    invites, bad = [], []
    for name in ("", "hut", "Καλημέρα", "x" * NAME_MAX):
        p = invite(g2, name)
        assert read_invite(p) == (g2, name)
        invites.append({"group_secret": g2.hex(), "name": name, "plaintext": p.hex()})
    for name, p in [
        ("short", invite(g2, "")[:-1]),
        ("long", invite(g2, "x" * NAME_MAX) + b"x"),
        ("not-utf-8", invite(g2, "") + b"\xff\xfe"),
        ("cut-mid-character", invite(g2, "é")[:-1]),
        ("another-kind", b"\x02" + invite(g2, "hut")[1:]),
        ("empty", b""),
    ]:
        assert read_invite(p) is None
        bad.append({"name": name, "plaintext": p.hex()})

    return {
        "description": "Groups, draft 0 (draft/groups.md). Secrets, nonces, frames and content are "
        "hex; routing ids (from, self) and hops are numbers, and power is signed. hops and power "
        "are the flood's (draft/flooding.md), and are 5 and 14 where a case does not give them. "
        "self is the routing id of the node receiving. In members, group is the index in groups "
        "of the group a frame is accepted for. hdr is 0x60 for a frame of words and 0x61 for one "
        "for the node, as node says. In recent, the frames with nonces first to "
        "first + count - 1, each as eight bytes most significant first, are from, content, hops "
        "and power sealed under group_secret. In invites and bad_invites, plaintext is that of a "
        "unicast message whose hdr has the node flag set (draft/unicast-security.md).",
        "generator": "vectors/tools/groups.py",
        "accepted": accepted,
        "rejected": rejected,
        "members": members,
        "recent": recent,
        "invites": invites,
        "bad_invites": bad,
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
