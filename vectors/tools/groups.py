#!/usr/bin/env python3
"""Generates and checks the group test vectors (draft/groups.md).

    python3 vectors/tools/groups.py generate   # rewrite vectors/groups.json
    python3 vectors/tools/groups.py check      # fail if the file differs from what this computes

Needs the `cryptography` package. Its primitives are unicast.py's, beside this file, which checks
them against RFC 5869 and RFC 3610 before anything is computed.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sharing  # noqa: E402
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
INSIDE = 8  # from and count, before the content
MIN_FRAME = BODY + INSIDE + TAG_LEN  # 31
MAX_FRAME = 255
WRITERS = 16
WINDOW = 32
RESERVED = (0, 0xFFFFFFFF)
KIND_INVITE = 0x01
NAME_MAX = 31
FLOOD = {"hops": 5, "power": 14}


def group_key(g):
    return unicast.expand(g, b"tern v0 group frame", 16)


def tag_key(g):
    return unicast.expand(g, b"tern v0 group tag", 16)


def gtag(g, n):
    enc = Cipher(algorithms.AES(tag_key(g)), modes.ECB()).encryptor()
    return (enc.update(bytes(8) + n) + enc.finalize())[:4]


def seal(g, n, sender, count, content, flood=FLOOD, hdr=HDR):
    assert len(g) == 16 and len(n) == 8 and len(content) <= MAX_FRAME - MIN_FRAME and hdr in HDRS
    t = gtag(g, n)
    plaintext = struct.pack(">II", sender, count) + content
    ct = AESCCM(group_key(g), tag_length=TAG_LEN).encrypt(bytes(5) + n, plaintext, bytes([hdr]) + n + t)
    return struct.pack(">BBb", hdr, flood["hops"], flood["power"]) + n + t + ct


def matches(g, frame):
    return (MIN_FRAME <= len(frame) <= MAX_FRAME and frame[0] in HDRS
            and frame[GTAG:BODY] == gtag(g, frame[NONCE:GTAG]))


def open_frame(g, me, frame):
    """A member's check, but for the writers it holds: (from, count, content), or None. Whether
    content is for the node is frame[0] & 1."""
    if not matches(g, frame):
        return None
    n = frame[NONCE:GTAG]
    try:
        p = AESCCM(group_key(g), tag_length=TAG_LEN).decrypt(
            bytes(5) + n, frame[BODY:], frame[0:1] + n + frame[GTAG:BODY])
    except Exception:
        return None
    sender, count = struct.unpack(">II", p[:INSIDE])
    if sender in RESERVED or sender == me:
        return None
    return sender, count, p[INSIDE:]


class Member:
    """A node and the groups it holds: which frames it accepts, each once."""

    def __init__(self, me, secrets):
        self.me, self.secrets = me, secrets
        # For each group, its writers: a routing id to the highest count accepted, every count
        # accepted in the window, and when a frame was last accepted from it.
        self.writers = [{} for _ in secrets]
        self.accepted = 0

    def fresh(self, i, sender, count):
        """Whether a frame of group i with this from and count is accepted, keeping it if so."""
        held = self.writers[i]
        top, had = count, set()
        if sender in held:
            top, had, _ = held[sender]
            if count <= top - WINDOW or count in had:
                return False
            top = max(top, count)
        self.accepted += 1
        held[sender] = (top, {c for c in had | {count} if c > top - WINDOW}, self.accepted)
        if len(held) > WRITERS:
            del held[min(held, key=lambda w: held[w][2])]
        return True

    def receive(self, frame):
        """(index of the group, from, count, content) if the frame is accepted, else None."""
        for i, g in enumerate(self.secrets):
            got = open_frame(g, self.me, frame)
            if got is not None and self.fresh(i, got[0], got[1]):
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


JOIN_LINK = "HTTPS://TERNMESH.ORG/G#"
JOIN_LABEL = b"tern group code"
PAYLOAD_MIN, PAYLOAD_MAX = 18, 18 + NAME_MAX


def join_payload(g, name):
    """A join code's payload: the secret, its check, and the name."""
    assert len(g) == 16 and len(name.encode()) <= NAME_MAX
    raw = name.encode()
    return g + hashlib.sha256(JOIN_LABEL + g + raw).digest()[:2] + raw


def join_link(g, name):
    return JOIN_LINK + sharing.b32(join_payload(g, name))


def unb32_any(s):
    """Canonical base32 of any length, either case, as bytes; None for anything else."""
    s = s.upper()
    if not s or any(ch not in sharing.BASE32 for ch in s):
        return None
    bits = 5 * len(s)
    whole, spare = divmod(bits, 8)
    if spare >= 5:  # a character that carries no bit of any byte
        return None
    n = 0
    for ch in s:
        n = n << 5 | sharing.BASE32.index(ch)
    if n & ((1 << spare) - 1):
        return None
    return (n >> spare).to_bytes(whole, "big")


def read_join(s):
    """(secret, name) from a join code, or None. Only ASCII is looked at, and the scheme, host and
    path are taken in either case, as an address's link is."""
    if not s.isascii() or s[: len(JOIN_LINK)].upper() != JOIN_LINK:
        return None
    p = unb32_any(s[len(JOIN_LINK) :])
    if p is None or not PAYLOAD_MIN <= len(p) <= PAYLOAD_MAX:
        return None
    g, check, raw = p[:16], p[16:18], p[18:]
    if hashlib.sha256(JOIN_LABEL + g + raw).digest()[:2] != check:
        return None
    try:
        return g, raw.decode("utf-8")
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


def case(name, note, g, n, sender, count, content, flood=FLOOD, me=0x0A0B0C0D, hdr=HDR):
    frame = seal(g, n, sender, count, content, flood, hdr)
    assert open_frame(g, me, frame) == (sender, count, content)
    return {
        "name": name,
        "note": note,
        "hdr": hdr,
        "node": hdr == HDR_NODE,
        "group_secret": g.hex(),
        "nonce": n.hex(),
        "from": sender,
        "count": count,
        "content": content.hex(),
        **flood,
        "self": me,
        "intermediate": {
            "group_key": group_key(g).hex(),
            "tag_key": tag_key(g).hex(),
            "gtag": gtag(g, n).hex(),
            "ccm_nonce": (bytes(5) + n).hex(),
            "associated_data": (bytes([hdr]) + n + gtag(g, n)).hex(),
            "plaintext": (struct.pack(">II", sender, count) + content).hex(),
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
        case("first", "a short message, the writer's first", g1, n1, alice, 0, hello),
        case("another-nonce", "the same words again, as the writer's next frame: nothing in the "
             "frame is as before", g1, bytes.fromhex("f0e1d2c3b4a59687"), alice, 1, hello),
        case("another-group", "the same nonce and count under another secret", g2, n1, alice, 0, hello),
        case("passed-on", "hops and power as a relay left them; not authenticated", g1, n1, alice, 0,
             hello, {"hops": 2, "power": -4}),
        case("empty", "no content: the 31-byte minimum frame", g1, bytes.fromhex("1111111111111111"),
             alice, 0x01020304, b""),
        case("non-latin", "UTF-8 text outside Latin script", g2, bytes.fromhex("2222222222222222"),
             0xFFFFFFFE, 70000, "Καλημέρα".encode()),
        case("largest", "224 bytes of content: a 255-byte frame, with the last count there is", g2,
             bytes.fromhex("3333333333333333"), 1, 0xFFFFFFFF,
             bytes(i & 0xFF for i in range(MAX_FRAME - MIN_FRAME))),
        case("for-the-node", "the node flag set: content is for the node, here a position "
             "(draft/positions.md) of a town", g1, bytes.fromhex("4444444444444444"), alice, 2,
             bytes.fromhex("0260" "8a6b80"), hdr=HDR_NODE),
        case("for-the-node-unknown-kind", "the node flag set and a kind no section defines: "
             "accepted, and nothing more done with it", g1, bytes.fromhex("5555555555555555"),
             alice, 3, b"\x7f", hdr=HDR_NODE),
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

    def sealed_with(key, plaintext, hdr=HDR):
        """A frame whose plaintext or key is not what seal() would give it."""
        ct = AESCCM(key, tag_length=TAG_LEN).encrypt(bytes(5) + n1, plaintext,
                                                    bytes([hdr]) + n1 + gtag(g1, n1))
        return struct.pack(">BBb", hdr, 5, 14) + n1 + gtag(g1, n1) + ct

    reject("check-flipped", "last bit of the AEAD tag changed", flip(-1))
    reject("ciphertext-flipped", "first ciphertext bit changed", flip(BODY, 0x80))
    reject("count-flipped", "a bit of the sealed count changed", flip(BODY + 7))
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
    reject("reserved-flag-sealed", "a reserved flag set, and sealed with it rightly: not a group "
           "frame of this draft",
           sealed_with(group_key(g1), struct.pack(">II", alice, 0) + hello, HDR | 4))
    reject("a-message", "a unicast message's header on it", bytes([0x48]) + frame[1:])
    reject("truncated", "30 bytes: shorter than any frame", frame[:MIN_FRAME - 1])
    reject("another-group", "a frame of a group this node does not hold",
           bytes.fromhex(accepted[2]["frame"]))
    reject("from-nobody", "from is 0x00000000: sealed rightly, and refused", seal(g1, n1, 0, 0, hello))
    reject("from-everyone", "from is 0xFFFFFFFF", seal(g1, n1, 0xFFFFFFFF, 0, hello))
    reject("from-itself", "from is the receiver's own routing id: another member writing as it",
           seal(g1, n1, me, 0, hello))
    reject("no-from", "three bytes of plaintext, sealed rightly: 26 bytes",
           sealed_with(group_key(g1), b"\x01\x02\x03"))
    reject("no-count", "from and three bytes more, sealed rightly: 30 bytes",
           sealed_with(group_key(g1), struct.pack(">I", alice) + b"\x00\x00\x00"))
    old = sealed_with(unicast.expand(g1, b"tern v0 group key", 16), struct.pack(">I", alice) + hello)
    assert len(old) >= MIN_FRAME and matches(g1, old)
    reject("first-draft", "a frame as this section was first drafted, with no count and under the "
           "key of the label \"tern v0 group key\": the tag is the group's, and the check fails", old)

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
                d.update({"group": got[0], "from": got[1], "count": got[2], "content": got[3].hex()})
            deliveries.append(d)
        members.append({"name": name, "note": note, "self": who,
                        "groups": [g.hex() for g in secrets], "deliveries": deliveries})
        return deliveries

    n2 = bytes.fromhex("0001020304050608")
    f1 = seal(g1, n1, alice, 7, hello)
    f2 = seal(g2, n1, alice, 7, b"two")
    d = member("two-groups", "frames of each group, of neither, and one a second time", me, [g1, g2],
               [f1, f2, seal(secret(7), n1, alice, 7, hello), f1, seal(g1, n2, alice, 8, hello)])
    assert [x["accept"] for x in d] == [True, True, False, False, True]
    d = member("again-passed-on", "a copy that came another way, hops and power changed: the same frame",
               me, [g1], [f1, seal(g1, n1, alice, 7, hello, {"hops": 1, "power": 3})])
    assert [x["accept"] for x in d] == [True, False]
    d = member("tags-collide", "two groups whose tags for this nonce are the same four bytes: a frame "
               f"of each (the secrets are the first 16 bytes of SHA-256(\"tern group\" || u32be(i)) for i = {a} and {b})",
               me, [ga, gb], [seal(gb, bytes(8), alice, 0, b"second"), seal(ga, bytes(8), alice, 0, b"first")])
    assert [x.get("group") for x in d] == [1, 0]
    for_node = seal(g1, bytes.fromhex("6666666666666666"), alice, 5, b"\x02\x00", hdr=HDR_NODE)
    d = member("node-and-words-one-count", "a frame for the node and one of words take their counts "
               "from one: words with the count a frame for the node had are refused, and the next "
               "are not", me, [g1],
               [for_node, seal(g1, bytes.fromhex("6666666666666667"), alice, 5, hello),
                seal(g1, bytes.fromhex("6666666666666668"), alice, 6, hello)])
    assert [x["accept"] for x in d] == [True, False, True]
    d = member("same-count-two-groups", "a count accepted for one group does not stand against "
               "another's, from the same writer", me, [g1, g2], [f1, f2])
    assert [x["accept"] for x in d] == [True, True]
    d = member("same-count-two-writers", "nor one writer's against another's, in one group", me, [g1],
               [f1, seal(g1, n2, 0x2B3C4D5E, 7, hello)])
    assert [x["accept"] for x in d] == [True, True]

    counts = []

    def counted(name, note, frames, want):
        """frames is (from, count) for each, in order; want, whether each is accepted."""
        m = Member(me, [g1])
        deliveries = []
        for k, (who, c) in enumerate(frames):
            f = seal(g1, k.to_bytes(8, "big"), who, c, hello)
            deliveries.append({"from": who, "count": c, "frame": f.hex(),
                               "accept": m.receive(f) is not None})
        assert [x["accept"] for x in deliveries] == [bool(w) for w in want], \
            (name, [x["accept"] for x in deliveries])
        counts.append({"name": name, "note": note, "group_secret": g1.hex(), "self": me,
                       "content": hello.hex(), **FLOOD, "deliveries": deliveries})

    top = 2**32 - 1
    counted("window", "the highest accepted is 100, then 132: a count is accepted once, down to "
            "31 below the highest and no further",
            [(alice, c) for c in (100, 100, 99, 99, 69, 68, 132, 101, 100, 69, 131, 131, 133, 102, 101)],
            [1, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0])
    counted("first-count", "a writer's first frame is accepted whatever its count, and the window "
            "is counted from it",
            [(alice, 5000), (alice, 4969), (alice, 4968), (alice, 0), (alice, 5001)], [1, 1, 0, 0, 1])
    counted("from-nought", "counts below 31: the window stops at 0",
            [(alice, 5), (alice, 0), (alice, 0), (alice, 4), (alice, 6)], [1, 1, 0, 1, 1])
    counted("skipped", "a writer may skip, however far: to the last count there is",
            [(alice, 0), (alice, top), (alice, top), (alice, top - 31), (alice, top - 32), (alice, 0),
             (alice, 1)], [1, 1, 0, 1, 0, 0, 0])
    bob = 0x2B3C4D5E
    counted("two-writers", "each writer's counts are its own",
            [(alice, 10), (bob, 10), (alice, 10), (bob, 9), (bob, 200), (alice, 11), (bob, 10)],
            [1, 1, 0, 1, 1, 1, 0])
    w = [0x70000000 + k for k in range(WRITERS + 1)]
    counted("writers", f"{WRITERS} writers held, then one more. The one forgotten is the one a frame "
            "was accepted from longest ago: the second, since the first wrote again, and a frame "
            "that is refused does not count. Its old frame is then accepted again, which forgets "
            "the third, whose own is accepted again in turn",
            [(x, 50) for x in w[:WRITERS]] + [(w[1], 50), (w[0], 51), (w[WRITERS], 1), (w[0], 50),
                                              (w[1], 50), (w[3], 50), (w[2], 50), (w[3], 50)],
            [1] * WRITERS + [0, 1, 1, 0, 1, 0, 1, 1])

    invites, bad = [], []
    joins, bad_joins = [], []
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

    # Join codes: for a group with no name, a short one, one in another script, and the longest.
    for name in ("", "Ridge walkers", "Καλημέρα", "x" * NAME_MAX):
        link = join_link(g2, name)
        assert sharing.b32(join_payload(g2, name)) == (
            base64.b32encode(join_payload(g2, name)).decode().rstrip("="))
        assert len(link) <= len(JOIN_LINK) + -(-8 * PAYLOAD_MAX // 5) == 102
        tail = link[len(JOIN_LINK) :]
        reads = [link.lower(), "https://ternmesh.org/g#" + tail, "Https://TernMesh.org/G#" + tail.lower()]
        for r in [link, *reads]:
            assert read_join(r) == (g2, name), r
        joins.append({"group_secret": g2.hex(), "name": name,
                      "payload": join_payload(g2, name).hex(), "link": link, "reads": reads})
    good = join_link(g2, "Hut")
    tail = good[len(JOIN_LINK) :]
    p = join_payload(g2, "Hut")
    for why, link in [
        ("another scheme", "HTTP://TERNMESH.ORG/G#" + tail),
        ("another host", "HTTPS://TERNMESH.NET/G#" + tail),
        ("an address's path", "HTTPS://TERNMESH.ORG/A#" + tail),
        ("in the path, not after a #", "HTTPS://TERNMESH.ORG/G/" + tail),
        ("a character that is not base32", good[:-1] + "1"),
        ("a last character whose spare bits are not zero", JOIN_LINK + tail[:-1]
         + sharing.BASE32[sharing.BASE32.index(tail[-1]) | 1]),
        ("a character too many", good + "A"),
        ("a payload too short", JOIN_LINK + sharing.b32(p[:17])),
        ("a payload too long", JOIN_LINK + sharing.b32(join_payload(g2, "x" * NAME_MAX) + b"x")),
        ("a check that is wrong", JOIN_LINK + sharing.b32(p[:16] + bytes([p[16] ^ 1]) + p[17:])),
        ("a secret with a letter wrong", JOIN_LINK + sharing.b32(bytes([p[0] ^ 0x10]) + p[1:])),
        ("a name that is not UTF-8", JOIN_LINK + sharing.b32(
            g2 + hashlib.sha256(JOIN_LABEL + g2 + b"\xff").digest()[:2] + b"\xff")),
        ("a dotless i, which upper-cases to an I", "HTTPS://TERNMESH.ORG/G#" + tail.replace(
            "I", "\u0131", 1) if "I" in tail else "HTTPS://TERNMESH.ORG/G#\u0131" + tail[1:]),
        ("empty after the #", JOIN_LINK),
    ]:
        assert read_join(link) is None, why
        bad_joins.append({"why": why, "link": link})

    return {
        "description": "Groups, draft 0 (draft/groups.md). Secrets, nonces, frames and content are "
        "hex; routing ids (from, self) and hops are numbers, and power is signed. hops and power "
        "are the flood's (draft/flooding.md), and are 5 and 14 where a case does not give them. "
        "self is the routing id of the node receiving. In members, group is the index in groups "
        "of the group a frame is accepted for. hdr is 0x60 for a frame of words and 0x61 for one "
        "for the node, as node says. count is a number. In counts, each delivery's frame is content "
        "from its from, with its count, sealed under group_secret with hops and power, and with a "
        "nonce of its place in deliveries, from 0, as eight bytes most significant first; frame "
        "gives it. In invites and bad_invites, plaintext is that of a "
        "unicast message whose hdr has the node flag set (draft/unicast-security.md). In "
        "join_codes, payload is the code's, link is how it is shown, and reads are other ways it "
        "is written that read as the same code; each of bad_join_codes reads as none.",
        "generator": "vectors/tools/groups.py",
        "accepted": accepted,
        "rejected": rejected,
        "members": members,
        "counts": counts,
        "invites": invites,
        "bad_invites": bad,
        "join_codes": joins,
        "bad_join_codes": bad_joins,
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
