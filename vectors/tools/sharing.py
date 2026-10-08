#!/usr/bin/env python3
"""Generates and checks the sharing test vectors (draft/sharing.md).

    python3 vectors/tools/sharing.py generate   # rewrite vectors/sharing.json
    python3 vectors/tools/sharing.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. The addresses are the valid ones in
first-contact.json, beside this file's output, so every case is an address a node could have.
Before computing anything it checks SHA-256 against the two-block message of FIPS 180-2,
appendix B.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import json
import sys
from pathlib import Path

VECTORS = Path(__file__).resolve().parent.parent
OUT = VECTORS / "sharing.json"

SHORT_CODE_LABEL = b"tern short code"
SCHEME = "TERN:"
DIGITS = 12


def self_check():
    """SHA-256 against FIPS 180-2's published values, before anything is computed with it."""
    assert (
        hashlib.sha256(b"abc").hexdigest()
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert (
        hashlib.sha256(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq").hexdigest()
        == "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
    )


def text(address: bytes) -> str:
    """An address written down: sixty-four upper-case hex digits."""
    return address.hex().upper()


def link(address: bytes) -> str:
    """An address as a link, and as a QR code holds it."""
    return SCHEME + text(address)


def code_value(address: bytes) -> int:
    h = hashlib.sha256(SHORT_CODE_LABEL + address).digest()
    return int.from_bytes(h[0:8], "big") % 10**DIGITS


def code_text(value: int) -> str:
    """Twelve decimal digits, leading zeros kept, in three groups of four."""
    d = "%0*d" % (DIGITS, value)
    return " ".join(d[i : i + 4] for i in range(0, DIGITS, 4))


def read(s: str):
    """What a reader takes an address from: the link, in any case, or the bare digits, in any
    case, with spaces anywhere among them. None for anything else."""
    if s[: len(SCHEME)].upper() == SCHEME:
        s = s[len(SCHEME) :]
    digits = s.replace(" ", "")
    if len(digits) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digits):
        return None
    return bytes.fromhex(digits)


def addresses():
    """Every distinct valid address first-contact.json holds, in the order it first holds them."""
    fc = json.loads((VECTORS / "first-contact.json").read_text())
    found = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.endswith("address") and isinstance(v, str) and len(v) == 64:
                    a = bytes.fromhex(v)
                    if a not in found:
                        found.append(a)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(fc["addresses"])
    walk(fc["handshakes"])
    return found


def build():
    self_check()
    cases = []
    for a in addresses():
        t = text(a)
        grouped = " ".join(t[i : i + 8] for i in range(0, 64, 8))
        reads = [link(a), t, t.lower(), "tern:" + t.lower(), "Tern:" + grouped, grouped]
        for r in reads:
            assert read(r) == a
        cases.append(
            {
                "address": a.hex(),
                "text": t,
                "link": link(a),
                "short_code": code_text(code_value(a)),
                "reads": reads,
            }
        )

    a = addresses()[0]
    t = text(a)
    refused = [
        t[:-1],  # sixty-three digits
        t + "0",  # sixty-five
        t[:-1] + "G",  # not hex
        "TERN:" + t[:-1],
        "TERN://" + t,  # not the form a link takes
        "TERM:" + t,
        "0x" + t,
        "",
        "TERN:",
    ]
    for r in refused:
        assert read(r) is None

    # The short code's form, on values chosen for it, so that leading zeros are seen kept.
    forms = [0, 42, 10**8, 10**12 - 1, 123456789012]
    formatting = [{"value": v, "text": code_text(v)} for v in forms]
    assert code_text(42) == "0000 0000 0042"

    return {
        "description": "Sharing an address off the air (draft/sharing.md): an address written "
        "down, as a link and in a QR code, and the short code two people compare. Addresses are "
        "first-contact.json's. Hex strings are bytes; text fields are exact.",
        "generator": "vectors/tools/sharing.py",
        "short_code_label": SHORT_CODE_LABEL.decode(),
        "cases": cases,
        "refused": refused,
        "short_code_forms": formatting,
    }


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("generate", "check"):
        sys.exit(__doc__)
    out = json.dumps(build(), indent=2) + "\n"
    if sys.argv[1] == "generate":
        OUT.write_text(out)
        print(f"wrote {OUT}")
    elif OUT.read_text() != out:
        sys.exit(f"{OUT} differs from what {Path(__file__).name} computes: run it with generate")
    else:
        print(f"{OUT.name} matches")


if __name__ == "__main__":
    main()
