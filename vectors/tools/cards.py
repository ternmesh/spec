#!/usr/bin/env python3
"""Generates and checks the presence card test vectors (draft/cards.md).

    python3 vectors/tools/cards.py generate   # rewrite vectors/cards.json
    python3 vectors/tools/cards.py check      # fail if the file differs from what this computes

Needs the Python `cryptography` package, for Ed25519. Before computing anything it checks
Ed25519 against RFC 8032's first two test vectors (section 7.1). The seeds are those of
first-contact.json, so every card is one a node with that address could send.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_contact import valid_address  # noqa: E402

VECTORS = Path(__file__).resolve().parent.parent
OUT = VECTORS / "cards.json"

HDR = 0x68  # format 01, type 101 (card), flags 000
LABEL = b"tern v0 card"
NAME_MAX = 31
MIN_LEN = 3 + 32 + 4 + 64  # head, address, number, signature: a card with no name
CARD_HOPS = 2
NEUTRAL = bytes([1]) + bytes(31)  # the encoding of the neutral point, RFC 8032 5.1.2
ORDER_8 = bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05")
FLOOD_HOPS = 5


def self_check():
    """Ed25519 against RFC 8032, section 7.1, TEST 1 and TEST 2."""
    cases = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
         "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
         "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]
    for seed, public, msg, sig in cases:
        assert address(bytes.fromhex(seed)).hex() == public
        assert sign(bytes.fromhex(seed), bytes.fromhex(msg)).hex() == sig


def address(seed: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def sign(seed: bytes, msg: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


def signed(hdr: int, addr: bytes, number: int, name: bytes) -> bytes:
    """What the signature covers: the label, then the frame but for hops, power and itself."""
    return LABEL + bytes([hdr]) + addr + number.to_bytes(4, "big") + name


def card(seed: bytes, number: int, name: bytes, hops: int, power: int) -> bytes:
    addr = address(seed)
    sig = sign(seed, signed(HDR, addr, number, name))
    return bytes([HDR, hops, power & 0xFF]) + addr + number.to_bytes(4, "big") + name + sig


def read(frame: bytes, own: bytes):
    """A card as a receiver takes it: (address, number, name), or None if it MUST be discarded.
    Whether it is newer than one already held is the caller's to say."""
    if len(frame) < MIN_LEN or len(frame) > MIN_LEN + NAME_MAX or frame[0] != HDR:
        return None
    addr, number = frame[3:35], int.from_bytes(frame[35:39], "big")
    name, sig = frame[39:-64], frame[-64:]
    if addr == own or not valid_address(addr):
        return None
    try:
        name.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        Ed25519PublicKey.from_public_bytes(addr).verify(sig, signed(frame[0], addr, number, name))
    except (InvalidSignature, ValueError):
        return None
    return addr, number, name


def seeds():
    fc = json.loads((VECTORS / "first-contact.json").read_text())
    return [bytes.fromhex(a["seed"]) for a in fc["addresses"]]


def build():
    self_check()
    s = seeds()
    own = address(s[1])

    accepted = []
    for seed, number, name, hops, power in [
        (s[0], 1, "Ada", CARD_HOPS, 20),
        (s[0], 0x01020304, "", CARD_HOPS, -9),
        (s[2], 7, "Trail crew · ask me", 1, 14),
        (s[2], 0xFFFFFFFF, "x" * NAME_MAX, 0, 2),
        (s[0], 2, "テルン", CARD_HOPS, 22),
    ]:
        name_b = name.encode("utf-8")
        frame = card(seed, number, name_b, hops, power)
        assert read(frame, own) == (address(seed), number, name_b)
        accepted.append({
            "seed": seed.hex(), "address": address(seed).hex(), "number": number,
            "name": name, "hops": hops, "power": power,
            "signed": signed(HDR, address(seed), number, name_b).hex(),
            "frame": frame.hex(),
        })

    good = card(s[0], 5, b"Ada", CARD_HOPS, 20)
    flip = bytearray(good)
    flip[-1] ^= 0x01
    renamed = bytearray(card(s[0], 5, b"Bob", CARD_HOPS, 20))
    renamed[39:42] = b"Eve"  # the name changed after signing
    renumbered = bytearray(good)
    renumbered[38] ^= 0x01
    rehdr = bytearray(good)
    rehdr[0] = 0x6C  # a flag set: not a card this draft defines
    bad_utf8 = card(s[0], 5, b"\xc3\x28", CARD_HOPS, 20)
    too_long = card(s[0], 5, b"y" * (NAME_MAX + 1), CARD_HOPS, 20)
    rejected = [
        ("the signature changed", bytes(flip)),
        ("the name changed after signing", bytes(renamed)),
        ("the number changed after signing", bytes(renumbered)),
        ("a header this draft does not define", bytes(rehdr)),
        ("a name that is not UTF-8, though signed", bad_utf8),
        ("a name of 32 bytes, though signed", too_long),
        ("one byte short of a card with no name", good[:MIN_LEN - 1]),
        ("the receiver's own card", card(s[1], 5, b"Me", CARD_HOPS, 20)),
        # The neutral point as the address, the neutral point as R and 0 as S: the verification
        # equation holds for any message, so a verifier without weak-key checks would take it.
        ("an address that is the neutral point, with a signature any message passes",
         bytes([HDR, CARD_HOPS, 20]) + NEUTRAL + (5).to_bytes(4, "big") + b"Ada" + NEUTRAL
         + bytes(32)),
        ("an address of order 8, though its card is otherwise whole",
         bytes([HDR, CARD_HOPS, 20]) + ORDER_8 + (5).to_bytes(4, "big") + b"Ada" + bytes(64)),
    ]
    for _, frame in rejected:
        assert read(frame, own) is None
    # hops and power are outside the signature: a relay changes them, and the card still reads.
    moved = bytearray(good)
    moved[1], moved[2] = 0, 0xF7
    assert read(bytes(moved), own) is not None

    # Which of a run of cards a receiver keeps: a card is kept only if its number is above that
    # of the last card it kept from that address.
    held = {}
    deliveries = []
    for seed, number, name in [
        (s[0], 3, "Ada"), (s[0], 3, "Ada"), (s[0], 2, "Ada"), (s[2], 1, "Trail"),
        (s[0], 4, "Ada L."), (s[2], 1, "Trail"), (s[2], 0xFFFFFFFF, "Trail"), (s[0], 1, "Ada"),
    ]:
        frame = card(seed, number, name.encode(), CARD_HOPS, 20)
        addr, num, _ = read(frame, own)
        keep = num > held.get(addr, -1)
        if keep:
            held[addr] = num
        deliveries.append({"frame": frame.hex(), "keep": keep})

    return {
        "description": (
            "Presence cards, draft 0 (draft/cards.md). For each accepted case, a node given seed, "
            "number, name, hops and power MUST produce frame, whose signature is over signed; and "
            "a node whose address is self MUST accept frame and read address, number and name "
            "from it. Each rejected frame MUST be discarded by a node whose address is self, "
            "among them two whose address first-contact.json rejects. "
            "Given each of deliveries in order, holding no cards, a node whose address is self "
            "MUST keep exactly those whose keep is true. A card's hops and power are not signed: "
            "relayed_still_valid is good with them changed, and MUST be accepted."
        ),
        "generator": "vectors/tools/cards.py",
        "hdr": HDR,
        "label": LABEL.decode(),
        "self": own.hex(),
        "accepted": accepted,
        "rejected": [{"why": why, "frame": f.hex()} for why, f in rejected],
        "relayed_still_valid": bytes(moved).hex(),
        "deliveries": deliveries,
    }


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("generate", "check"):
        sys.exit(__doc__)
    out = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if sys.argv[1] == "generate":
        OUT.write_text(out)
        print(f"wrote {OUT}")
    elif OUT.read_text() != out:
        sys.exit(f"{OUT} differs from what {Path(__file__).name} computes: run it with generate")
    else:
        print(f"{OUT.name} matches")


if __name__ == "__main__":
    main()
