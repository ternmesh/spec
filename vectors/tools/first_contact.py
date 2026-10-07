#!/usr/bin/env python3
"""Generates and checks the first-contact test vectors (draft/first-contact.md).

    python3 vectors/tools/first_contact.py generate   # rewrite vectors/first-contact.json
    python3 vectors/tools/first_contact.py check      # fail if the file differs from what this computes

Needs the `cryptography` package. Before computing anything it checks itself: its EDHOC must
reproduce both of RFC 9529's traces exactly (method 0 with X25519 and Ed25519, and method 3 with
P-256), message by message and to PRK_out; and its conversion of each Ed25519 address to an X25519
key must agree with X25519 run on the key Ed25519 derives from the same seed.

Tern's two roles are written separately from the EDHOC core (`initiator_*`, `responder_*`), as a
receiver would implement them, and every handshake they produce is checked against the core.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

OUT = Path(__file__).resolve().parent.parent / "first-contact.json"

FORMAT_V0 = 0b01
TYPE_FIRST_CONTACT = 0b010
PREFIX = 8
EXPORTER_LABEL = 32768  # RFC 9528's private-use range, until Tern registers one
CTAG_LABEL = b"tern v0 contact"
METHOD = 3  # static DH on both sides
SUITE = 0  # AES-CCM-16-64-128, SHA-256, 8-byte MAC, X25519, EdDSA
KID_R = b"\x00"


def hdr(n: int) -> int:
    return (FORMAT_V0 << 6) | (TYPE_FIRST_CONTACT << 3) | n  # 0x51 to 0x54


# ---------------------------------------------------------------------------------------------
# CBOR, as much as EDHOC uses


def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    if n < 0x100:
        return bytes([major << 5 | 24, n])
    if n < 0x10000:
        return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
    return bytes([major << 5 | 26]) + n.to_bytes(4, "big")


def cbor(x) -> bytes:
    if isinstance(x, int):
        return _head(0, x) if x >= 0 else _head(1, -1 - x)
    if isinstance(x, bytes):
        return _head(2, len(x)) + x
    if isinstance(x, str):
        return _head(3, len(x.encode())) + x.encode()
    if isinstance(x, list):
        return _head(4, len(x)) + b"".join(cbor(i) for i in x)
    if isinstance(x, dict):
        return _head(5, len(x)) + b"".join(cbor(k) + cbor(v) for k, v in x.items())
    raise TypeError(x)


def one_byte_int(b: bytes) -> bool:
    return len(b) == 1 and (b[0] <= 0x17 or 0x20 <= b[0] <= 0x37)


def conn_id(raw: bytes) -> bytes:
    return raw if one_byte_int(raw) else cbor(raw)


def compact(id_cred: bytes, kid):
    if kid is None:
        return id_cred
    return kid if one_byte_int(kid) else cbor(kid)


# ---------------------------------------------------------------------------------------------
# EDHOC (RFC 9528): the core, for any method, with SHA-256 and AES-CCM-16-64-128


def H(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def expand(prk: bytes, info: bytes, length: int) -> bytes:
    return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=info).derive(prk)


def kdf(prk: bytes, label: int, context: bytes, length: int) -> bytes:
    return expand(prk, cbor(label) + cbor(context) + cbor(length), length)


MAC_LEN, TAG_LEN, KEY_LEN, IV_LEN, HASH_LEN = 8, 8, 16, 13, 32


def seal(k, iv, th, pt):
    return AESCCM(k, tag_length=TAG_LEN).encrypt(iv, pt, cbor(["Encrypt0", b"", th]))


def unseal(k, iv, th, ct):
    try:
        return AESCCM(k, tag_length=TAG_LEN).decrypt(iv, ct, cbor(["Encrypt0", b"", th]))
    except InvalidTag:
        return None


class X25519:
    @staticmethod
    def public(priv):
        return X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes_raw()

    @staticmethod
    def dh(priv, pub):
        # The library refuses an all-zero result; RFC 9528 9.2 requires that refusal (RFC 7748 6.1).
        try:
            return X25519PrivateKey.from_private_bytes(priv).exchange(X25519PublicKey.from_public_bytes(pub))
        except ValueError:
            return None


class P256:  # only for replaying RFC 9529's second trace
    @staticmethod
    def _key(priv):
        return ec.derive_private_key(int.from_bytes(priv, "big"), ec.SECP256R1())

    @staticmethod
    def public(priv):
        return P256._key(priv).public_key().public_numbers().x.to_bytes(32, "big")

    @staticmethod
    def dh(priv, pub):
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x02" + pub)
        return P256._key(priv).exchange(ec.ECDH(), peer)


def sign1(seed, id_cred, ext_aad, payload):
    return Ed25519PrivateKey.from_private_bytes(seed).sign(cbor(["Signature1", id_cred, ext_aad, payload]))


def edhoc(curve, method, suites_i, x, y, c_i, c_r, id_cred_i, kid_i, cred_i, id_cred_r, kid_r, cred_r, sk_i, sk_r):
    """Both ends of one EDHOC session, as RFC 9529 lays it out. id_cred_* are encoded maps, kid_* the
    kid when the map is {4: kid}, cred_* encoded credentials, sk_* static DH private keys (or Ed25519
    seeds, for a side that signs). Returns the messages and the values RFC 9529 publishes."""
    v = {}
    i_signs, r_signs = method in (0, 1), method in (0, 2)
    g_x, g_y = curve.public(x), curve.public(y)
    v["message_1"] = cbor(method) + cbor(suites_i) + cbor(g_x) + conn_id(c_i)
    th_2 = H(cbor(g_y) + cbor(H(v["message_1"])))
    prk_2e = extract(th_2, curve.dh(y, g_x))
    prk_3e2m = prk_2e if r_signs else extract(kdf(prk_2e, 1, th_2, HASH_LEN), curve.dh(sk_r, g_x))
    mac_2 = kdf(prk_3e2m, 2, conn_id(c_r) + id_cred_r + cbor(th_2) + cred_r, HASH_LEN if r_signs else MAC_LEN)
    sm_2 = sign1(sk_r, id_cred_r, cbor(th_2) + cred_r, mac_2) if r_signs else mac_2
    pt_2 = conn_id(c_r) + compact(id_cred_r, kid_r) + cbor(sm_2)
    ks = kdf(prk_2e, 0, th_2, len(pt_2))
    v["message_2"] = cbor(g_y + bytes(a ^ b for a, b in zip(pt_2, ks)))
    th_3 = H(cbor(th_2) + pt_2 + cred_r)
    if i_signs:
        prk_4e3m = prk_3e2m
    else:
        prk_4e3m = extract(kdf(prk_3e2m, 5, th_3, HASH_LEN), curve.dh(y, curve.public(sk_i)))
    mac_3 = kdf(prk_4e3m, 6, id_cred_i + cbor(th_3) + cred_i, HASH_LEN if i_signs else MAC_LEN)
    sm_3 = sign1(sk_i, id_cred_i, cbor(th_3) + cred_i, mac_3) if i_signs else mac_3
    pt_3 = compact(id_cred_i, kid_i) + cbor(sm_3)
    k_3, iv_3 = kdf(prk_3e2m, 3, th_3, KEY_LEN), kdf(prk_3e2m, 4, th_3, IV_LEN)
    v["message_3"] = cbor(seal(k_3, iv_3, th_3, pt_3))
    th_4 = H(cbor(th_3) + pt_3 + cred_i)
    k_4, iv_4 = kdf(prk_4e3m, 8, th_4, KEY_LEN), kdf(prk_4e3m, 9, th_4, IV_LEN)
    v["message_4"] = cbor(seal(k_4, iv_4, th_4, b""))
    v["PRK_out"] = kdf(prk_4e3m, 7, th_4, HASH_LEN)
    v.update(TH_2=th_2, TH_3=th_3, TH_4=th_4)
    return v


# RFC 9529, values copied from the traces. Section 2 (trace 1): method 0, suite 0, X.509 by x5t.
# Section 3 (trace 2): method 3, suite 2, CCSs by kid; its second, successful message_1.
TRACE_1 = {
    "X": "892ec28e5cb6669108470539500b705e60d008d347c5817ee9f3327c8a87bb03",
    "Y": "e69c23fbf81bc435942446837fe827bf206c8fa10a39db47449e5a813421e1e8",
    "SK_I": "4c5b25878f507c6b9dae68fbd4fd3ff997533db0af00b25d324ea28e6c213bc8",
    "SK_R": "ef140ff900b0ab03f0c08d879cbbd4b31ea71e6e7ee7ffcb7e7955777a332799",
    "C_I": "2d",
    "C_R": "18",
    "ID_CRED_I": "a11822822e48c24ab2fd7643c79f",
    "ID_CRED_R": "a11822822e4879f2a41b510c1f9b",
    "CRED_I": (
        "58f13081ee3081a1a003020102020462319ea0300506032b6570301d311b301906035504030c12454448"
        "4f4320526f6f742045643235353139301e170d3232303331363038323430305a170d3239313233313233"
        "303030305a30223120301e06035504030c174544484f4320496e69746961746f72204564323535313930"
        "2a300506032b6570032100ed06a8ae61a829ba5fa54525c9d07f48dd44a302f43e0f23d8cc20b7308514"
        "1e300506032b6570034100521241d8b3a770996bcfc9b9ead4e7e0a1c0db353a3bdf2910b39275ae48b7"
        "56015981850d27db6734e37f67212267dd05eeff27b9e7a813fa574b72a00b430b"
    ),
    "CRED_R": (
        "58f13081ee3081a1a003020102020462319ec4300506032b6570301d311b301906035504030c12454448"
        "4f4320526f6f742045643235353139301e170d3232303331363038323433365a170d3239313233313233"
        "303030305a30223120301e06035504030c174544484f4320526573706f6e646572204564323535313930"
        "2a300506032b6570032100a1db47b95184854ad12a0c1a354e418aace33aa0f2c662c00b3ac55de92f93"
        "59300506032b6570034100b723bc01eab0928e8b2b6c98de19cc3823d46e7d6987b032478fecfaf14537"
        "a1af14cc8be829c6b73044101837eb4abc949565d86dce51cfae52ab82c152cb02"
    ),
    "message_1": "0000582031f82c7b5b9cbbf0f194d913cc12ef1532d328ef32632a4881a1c0701e237f042d",
    "message_2": (
        "5872dc88d2d51da5ed67fc4616356bc8ca74ef9ebe8b387e623a360ba480b9b29d1cbc26dd270fe9c02c"
        "44ce3934794b1cc62ba22f05459f8d358c8d12275ac42c5f96ded5f13cc9084e5b201889a45e5a60a556"
        "2dc118619c3daa2fd9f4c9f4d6edad109dd4edf95962aafbaf9ab3f4a1f6b98f"
    ),
    "message_3": (
        "585825c345884aaaeb22c527f9b1d2b6787207e0163c69b62a0d43928150427203c31674e4514ea6e383"
        "b566eb29763efeb0afa518776ae1c65f856d84bf32af3a7836970466dcb71f76745d39d3025e7703e0c0"
        "32ebad51947c"
    ),
    "message_4": "484f0edee366e5c883",
    "PRK_out": "b744cb7d8a87cc0447c3350e165b250dab12ec453325abb922b30307e5c368f0",
}
TRACE_2 = {
    "X": "368ec1f69aeb659ba37d5a8d45b21bdc0299dceaa8ef235f3ca42ce3530f9525",
    "Y": "e2f4126777205e853b437d6eaca1e1f753cdcc3e2c69fa884b0a1a640977e418",
    "SK_I": "fb13adeb6518cee5f88417660841142e830a81fe334380a953406a1305e8706b",
    "SK_R": "72cc4761dbd4c78f758931aa589d348d1ef874a7e303ede2f140dcf3e6aa4aac",
    "C_I": "37",
    "C_R": "27",
    "ID_CRED_I": "a104412b",
    "ID_CRED_R": "a1044132",
    "CRED_I": (
        "a2027734322d35302d33312d46462d45462d33372d33322d333908a101a5010202412b2001215820ac75"
        "e9ece3e50bfc8ed60399889522405c47bf16df96660a41298cb4307f7eb62258206e5de611388a4b8a82"
        "11334ac7d37ecb52a387d257e6db3c2a93df21ff3affc8"
    ),
    "CRED_R": (
        "a2026b6578616d706c652e65647508a101a501020241322001215820bbc34960526ea4d32e940cad2a23"
        "4148ddc21791a12afbcbac93622046dd44f02258204519e257236b2a0ce2023f0931f1f386ca7afda64f"
        "cde0108c224c51eabf6072"
    ),
    "message_1": "0382060258208af6f430ebe18d34184017a9a11bf511c8dff8f834730b96c1b7c8dbca2fc3b637",
    "message_2": (
        "582b419701d7f00a26c2dc587a36dd752549f33763c893422c8ea0f955a13a4ff5d59862a1eef9e0e7e1"
        "886fcd"
    ),
    "message_3": "52e562097bc417dd5919485ac7891ffd90a9fc",
    "message_4": "4828c966b7ca304f83",
    "PRK_out": "2c71afc1a9338a940bb3529ca734b886f30d1aba0b4dc51beeaeabdfea9ecbf8",
}


def _b(v):
    return bytes.fromhex("".join(v) if isinstance(v, tuple) else v)


def check_rfc9529():
    for n, t, curve, suites in ((1, TRACE_1, X25519, 0), (2, TRACE_2, P256, [6, 2])):
        t = {k: _b(v) for k, v in t.items()}
        kid = lambda idc: idc[3:] if idc[:2] == b"\xa1\x04" else None
        method = 0 if n == 1 else 3
        got = edhoc(
            curve, method, suites, t["X"], t["Y"], t["C_I"], t["C_R"],
            t["ID_CRED_I"], kid(t["ID_CRED_I"]), t["CRED_I"],
            t["ID_CRED_R"], kid(t["ID_CRED_R"]), t["CRED_R"], t["SK_I"], t["SK_R"],
        )  # fmt: skip
        for k in ("message_1", "message_2", "message_3", "message_4", "PRK_out"):
            assert got[k] == t[k], f"RFC 9529 trace {n}: {k} differs"


# ---------------------------------------------------------------------------------------------
# Addresses: Ed25519 public keys (RFC 8032), and the X25519 keys made from them

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493  # the prime order of the base point
D = -121665 * pow(121666, -1, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
NEUTRAL = (0, 1)


def decode(a: bytes):
    """RFC 8032 5.1.3: the point an encoding names, or None."""
    if len(a) != 32:
        return None
    y = int.from_bytes(a, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, -1, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = P - x
    return (x, y)


def encode(pt) -> bytes:
    x, y = pt
    return (y | (x & 1) << 255).to_bytes(32, "little")


def add(p1, p2):
    (x1, y1), (x2, y2) = p1, p2
    t = D * x1 * x2 * y1 * y2 % P
    return (
        (x1 * y2 + y1 * x2) * pow(1 + t, -1, P) % P,
        (y1 * y2 + x1 * x2) * pow(1 - t, -1, P) % P,
    )


def mul(k: int, pt):
    r = NEUTRAL
    while k:
        if k & 1:
            r = add(r, pt)
        pt, k = add(pt, pt), k >> 1
    return r


def valid_address(a: bytes) -> bool:
    """It decodes to a point of the prime-order subgroup other than the neutral element. A point
    with a small-order component T added would pass a check for small order alone, and X25519,
    whose scalars are multiples of 8, cannot tell A + T from A."""
    pt = decode(a)
    return pt is not None and pt != NEUTRAL and mul(L, pt) == NEUTRAL


def x25519_public(a: bytes) -> bytes:
    """The u-coordinate of the Montgomery point equivalent to A: u = (1 + y) / (1 - y)."""
    _, y = decode(a)
    return ((1 + y) * pow(1 - y, -1, P) % P).to_bytes(32, "little")


def address(seed: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()


def x25519_private(seed: bytes) -> bytes:
    """The first half of SHA-512(seed), which Ed25519 clamps into its scalar and X25519 clamps too."""
    return hashlib.sha512(seed).digest()[:32]


def check_conversion(seed: bytes):
    """Two routes to the same key: converting the address, and X25519 on the converted private key."""
    a = address(seed)
    assert decode(a) is not None and encode(decode(a)) == a
    assert x25519_public(a) == X25519.public(x25519_private(seed)), "address conversion"


# ---------------------------------------------------------------------------------------------
# Tern's profile


def cred(a: bytes) -> bytes:
    """CRED_x: a CWT Claims Set whose confirmation claim holds the address as an Ed25519 COSE_Key."""
    return cbor({8: {1: {1: 1, -1: 6, -2: a}}})


def id_cred_i(a: bytes) -> bytes:
    return b"\xa1\x0e" + cred(a)  # {14: CRED_I}, 'kccs'


ID_CRED_R = cbor({4: KID_R})
CRED_PREFIX = cred(bytes(32))[:-32]


def ctags(g_x: bytes, g_rx: bytes):
    prk = extract(g_x, g_rx)
    return {n: expand(prk, CTAG_LABEL + bytes([n]), 4) for n in (1, 2, 3, 4)}


def frame(n, ctag, message, hop=0, label=0):
    return bytes([hdr(n), hop]) + label.to_bytes(2, "big") + ctag + message


def initiator_start(seed, target, x, c_i):
    """message_1, to the node whose address is target."""
    assert valid_address(target)
    g_x = X25519.public(x)
    g_rx = X25519.dh(x, x25519_public(target))
    assert g_rx is not None
    m1 = cbor(METHOD) + cbor(SUITE) + cbor(g_x) + conn_id(c_i)
    st = dict(seed=seed, target=target, x=x, g_x=g_x, g_rx=g_rx, m1=m1, ctag=ctags(g_x, g_rx))
    return st, frame(1, st["ctag"][1], m1)


def responder_receive_1(seed, y, c_r, f):
    """message_2 in reply to f, or None if f is not a message_1 for this node, or fails."""
    if len(f) != PREFIX + 37 or f[0] != hdr(1):
        return None
    m1 = f[PREFIX:]
    if m1[:4] != b"\x03\x00\x58\x20" or not one_byte_int(m1[36:]):
        return None
    g_x = m1[4:36]
    g_rx = X25519.dh(x25519_private(seed), g_x)
    if g_rx is None:
        return None
    ct = ctags(g_x, g_rx)
    if f[4:8] != ct[1]:
        return None  # not for this node
    g_y = X25519.public(y)
    th_2 = H(cbor(g_y) + cbor(H(m1)))
    prk_2e = extract(th_2, X25519.dh(y, g_x))
    prk_3e2m = extract(kdf(prk_2e, 1, th_2, HASH_LEN), g_rx)
    cred_r = cred(address(seed))
    mac_2 = kdf(prk_3e2m, 2, conn_id(c_r) + ID_CRED_R + cbor(th_2) + cred_r, MAC_LEN)
    pt_2 = conn_id(c_r) + KID_R + cbor(mac_2)
    ks = kdf(prk_2e, 0, th_2, len(pt_2))
    m2 = cbor(g_y + bytes(a ^ b for a, b in zip(pt_2, ks)))
    st = dict(seed=seed, y=y, ctag=ct, prk_3e2m=prk_3e2m, th_3=H(cbor(th_2) + pt_2 + cred_r))
    return st, frame(2, ct[2], m2)


def initiator_receive_2(st, f, c_i):
    """message_3 in reply to f, or None if it fails."""
    if len(f) != PREFIX + 45 or f[0] != hdr(2) or f[4:8] != st["ctag"][2]:
        return None
    m2 = f[PREFIX:]
    if m2[:2] != b"\x58\x2b":
        return None
    g_y, ct_2 = m2[2:34], m2[34:]
    th_2 = H(cbor(g_y) + cbor(H(st["m1"])))
    g_xy = X25519.dh(st["x"], g_y)
    if g_xy is None:
        return None
    prk_2e = extract(th_2, g_xy)
    pt_2 = bytes(a ^ b for a, b in zip(ct_2, kdf(prk_2e, 0, th_2, len(ct_2))))
    c_r = pt_2[:1]
    if not one_byte_int(c_r) or pt_2[1:3] != KID_R + b"\x48":
        return None
    prk_3e2m = extract(kdf(prk_2e, 1, th_2, HASH_LEN), st["g_rx"])
    cred_r = cred(st["target"])
    mac_2 = kdf(prk_3e2m, 2, c_r + ID_CRED_R + cbor(th_2) + cred_r, MAC_LEN)
    if not hmac.compare_digest(mac_2, pt_2[3:]):
        return None
    th_3 = H(cbor(th_2) + pt_2 + cred_r)
    g_iy = X25519.dh(x25519_private(st["seed"]), g_y)
    if g_iy is None:
        return None
    prk_4e3m = extract(kdf(prk_3e2m, 5, th_3, HASH_LEN), g_iy)
    me = address(st["seed"])
    mac_3 = kdf(prk_4e3m, 6, id_cred_i(me) + cbor(th_3) + cred(me), MAC_LEN)
    pt_3 = id_cred_i(me) + cbor(mac_3)
    k_3, iv_3 = kdf(prk_3e2m, 3, th_3, KEY_LEN), kdf(prk_3e2m, 4, th_3, IV_LEN)
    m3 = cbor(seal(k_3, iv_3, th_3, pt_3))
    st.update(prk_4e3m=prk_4e3m, th_4=H(cbor(th_3) + pt_3 + cred(me)))
    return frame(3, st["ctag"][3], m3)


def responder_receive_3(st, f, check_address=True):
    """(message_4, the initiator's address, S), or None if f fails. check_address=False is only
    for showing that a rejected vector would otherwise be accepted."""
    if len(f) != PREFIX + 65 or f[0] != hdr(3) or f[4:8] != st["ctag"][3]:
        return None
    m3 = f[PREFIX:]
    if m3[:2] != b"\x58\x3f":
        return None
    th_3, prk_3e2m = st["th_3"], st["prk_3e2m"]
    k_3, iv_3 = kdf(prk_3e2m, 3, th_3, KEY_LEN), kdf(prk_3e2m, 4, th_3, IV_LEN)
    pt_3 = unseal(k_3, iv_3, th_3, m3[2:])
    if pt_3 is None or len(pt_3) != 55 or pt_3[:14] != b"\xa1\x0e" + CRED_PREFIX or pt_3[46:47] != b"\x48":
        return None
    a_i = pt_3[14:46]
    if check_address and not valid_address(a_i):
        return None
    g_iy = X25519.dh(st["y"], x25519_public(a_i))
    if g_iy is None:
        return None
    prk_4e3m = extract(kdf(prk_3e2m, 5, th_3, HASH_LEN), g_iy)
    mac_3 = kdf(prk_4e3m, 6, id_cred_i(a_i) + cbor(th_3) + cred(a_i), MAC_LEN)
    if not hmac.compare_digest(mac_3, pt_3[47:]):
        return None
    th_4 = H(cbor(th_3) + pt_3 + cred(a_i))
    k_4, iv_4 = kdf(prk_4e3m, 8, th_4, KEY_LEN), kdf(prk_4e3m, 9, th_4, IV_LEN)
    m4 = cbor(seal(k_4, iv_4, th_4, b""))
    return frame(4, st["ctag"][4], m4), a_i, session_secret(prk_4e3m, th_4)


def initiator_receive_4(st, f):
    """S, or None if f fails."""
    if len(f) != PREFIX + 9 or f[0] != hdr(4) or f[4:8] != st["ctag"][4] or f[8] != 0x48:
        return None
    prk_4e3m, th_4 = st["prk_4e3m"], st["th_4"]
    k_4, iv_4 = kdf(prk_4e3m, 8, th_4, KEY_LEN), kdf(prk_4e3m, 9, th_4, IV_LEN)
    if unseal(k_4, iv_4, th_4, f[9:]) != b"":
        return None
    return session_secret(prk_4e3m, th_4)


def session_secret(prk_4e3m, th_4):
    prk_out = kdf(prk_4e3m, 7, th_4, HASH_LEN)
    prk_exporter = kdf(prk_out, 10, b"", HASH_LEN)
    return kdf(prk_exporter, EXPORTER_LABEL, b"", 32)  # EDHOC_Exporter(label, h'', 32)


# ---------------------------------------------------------------------------------------------
# The vectors


def det(label: str, n: int = 32) -> bytes:
    """A fixed value for a vector input, so the file is reproducible."""
    return hashlib.sha256(b"tern first contact vectors " + label.encode()).digest()[:n]


def run(i_seed, r_seed, x, y, c_i, c_r):
    """A full handshake through the two roles, checked against the EDHOC core."""
    st_i, f1 = initiator_start(i_seed, address(r_seed), x, c_i)
    st_r, f2 = responder_receive_1(r_seed, y, c_r, f1)
    f3 = initiator_receive_2(st_i, f2, c_i)
    f4, a_i, s_r = responder_receive_3(st_r, f3)
    s_i = initiator_receive_4(st_i, f4)
    assert f3 and a_i == address(i_seed) and s_i == s_r
    core = edhoc(
        X25519, METHOD, SUITE, x, y, c_i, c_r,
        id_cred_i(address(i_seed)), None, cred(address(i_seed)),
        ID_CRED_R, KID_R, cred(address(r_seed)),
        x25519_private(i_seed), x25519_private(r_seed),
    )  # fmt: skip
    for n, f in enumerate((f1, f2, f3, f4), 1):
        assert f[PREFIX:] == core[f"message_{n}"], f"message_{n} differs from the EDHOC core"
    return dict(st_i=st_i, st_r=st_r, frames=(f1, f2, f3, f4), s=s_i, core=core)


def handshake_case(name, note, i_seed, r_seed, x, y, c_i, c_r):
    h = run(i_seed, r_seed, x, y, c_i, c_r)
    st_i = h["st_i"]
    return h, {
        "name": name,
        "note": note,
        "initiator_seed": i_seed.hex(),
        "responder_seed": r_seed.hex(),
        "initiator_ephemeral": x.hex(),
        "responder_ephemeral": y.hex(),
        "c_i": c_i.hex(),
        "c_r": c_r.hex(),
        "frames": [f.hex() for f in h["frames"]],
        "session_secret": h["s"].hex(),
        "intermediate": {
            "initiator_address": address(i_seed).hex(),
            "responder_address": address(r_seed).hex(),
            "g_x": st_i["g_x"].hex(),
            "g_y": X25519.public(y).hex(),
            "g_rx": st_i["g_rx"].hex(),
            "ctags": [st_i["ctag"][n].hex() for n in (1, 2, 3, 4)],
            "th_2": h["core"]["TH_2"].hex(),
            "th_3": h["core"]["TH_3"].hex(),
            "th_4": h["core"]["TH_4"].hex(),
            "prk_out": h["core"]["PRK_out"].hex(),
        },
    }


def small_order_points():
    """The eight points of order dividing 8, as [L]P for points P until all eight turn up."""
    found, i = set(), 0
    while len(found) < 8:
        pt = decode(det(f"torsion {i}"))
        i += 1
        if pt is not None:
            found.add(mul(L, pt))
    return sorted(found)


def build() -> dict:
    check_rfc9529()
    seeds = [det(f"seed {i}") for i in range(3)]
    for s in seeds:
        check_conversion(s)

    addresses = [
        {
            "seed": s.hex(),
            "address": address(s).hex(),
            "x25519_private": x25519_private(s).hex(),
            "x25519_public": x25519_public(address(s)).hex(),
        }
        for s in seeds
    ]

    rejected_addresses = []
    for pt in small_order_points():
        a = encode(pt)
        assert not valid_address(a)
        order = next(k for k in (1, 2, 4, 8) if mul(k, pt) == NEUTRAL)
        rejected_addresses.append({"address": a.hex(), "reason": f"a point of order {order}"})
    mixed = encode(add(decode(address(seeds[0])), small_order_points()[-1]))
    assert decode(mixed) is not None and mul(8, decode(mixed)) != NEUTRAL and not valid_address(mixed)
    rejected_addresses.append(
        {"address": mixed.hex(), "reason": "the first address plus a point of order 8: not of prime order"}
    )
    non_canonical = (P + 1).to_bytes(32, "little")  # y = p + 1, which is 1 reduced: not canonical
    assert decode(non_canonical) is None
    rejected_addresses.append({"address": non_canonical.hex(), "reason": "y is not reduced modulo p"})
    off = next(det(f"off {i}") for i in range(100) if decode(det(f"off {i}")) is None and det(f"off {i}")[31] < 0x7F)
    rejected_addresses.append({"address": off.hex(), "reason": "no point has this y"})

    i_seed, r_seed, other_seed = seeds
    h0, case0 = handshake_case(
        "first", "a handshake with small connection identifiers",
        i_seed, r_seed, det("x 0"), det("y 0"), b"\x00", b"\x01",
    )  # fmt: skip
    h1, case1 = handshake_case(
        "negative-ids", "the roles reversed, with negative connection identifiers",
        r_seed, i_seed, det("x 1"), det("y 1"), b"\x37", b"\x20",
    )  # fmt: skip
    _, case2 = handshake_case(
        "third", "a third node contacting the first",
        other_seed, i_seed, det("x 2"), det("y 2"), b"\x17", b"\x17",
    )  # fmt: skip

    f1, f2, f3, f4 = h0["frames"]

    # message_1 for one node, heard by another.
    assert responder_receive_1(other_seed, det("y 0"), b"\x01", f1) is None
    not_for_me = [
        {
            "name": "other-node",
            "note": "the first handshake's message_1, heard by a node it is not for",
            "responder_seed": other_seed.hex(),
            "frame": f1.hex(),
        }
    ]

    rejected = []

    def reject(name, note, message, f, check):
        assert check(f) is None, name
        rejected.append({"name": name, "note": note, "handshake": "first", "message": message, "frame": f.hex()})

    def flip(f, i):
        return f[:i] + bytes([f[i] ^ 0x01]) + f[i + 1 :]

    # Receiver states as of each message, fresh for each case.
    def as_responder(f):
        return responder_receive_1(r_seed, det("y 0"), b"\x01", f)

    def i_state():
        st, _ = initiator_start(i_seed, address(r_seed), det("x 0"), b"\x00")
        return st

    def r_state():
        st, _ = responder_receive_1(r_seed, det("y 0"), b"\x01", f1)
        return st

    def as_initiator_2(f):
        return initiator_receive_2(i_state(), f, b"\x00")

    def as_responder_3(f):
        return responder_receive_3(r_state(), f)

    def as_initiator_4(f):
        st = i_state()
        assert initiator_receive_2(st, f2, b"\x00")
        return initiator_receive_4(st, f)

    reject("message_1-ead", "message_1 with one byte of EAD padding: v0 carries none", 1, f1 + b"\x00", as_responder)
    reject("message_1-suites", "message_1 offering suites [6, 0]", 1,
           f1[:PREFIX + 1] + b"\x82\x06\x00" + f1[PREFIX + 2:], as_responder)  # fmt: skip
    reject("message_1-method", "message_1 with method 0 (signatures)", 1, f1[:PREFIX] + b"\x00" + f1[PREFIX + 1 :], as_responder)
    reject("message_2-ciphertext", "message_2 with a bit of CIPHERTEXT_2 flipped", 2, flip(f2, len(f2) - 1), as_initiator_2)
    reject("message_2-ctag", "message_2 with a bit of its tag flipped", 2, flip(f2, 4), as_initiator_2)
    reject("message_3-ciphertext", "message_3 with a bit of CIPHERTEXT_3 flipped", 3, flip(f3, 20), as_responder_3)
    reject("message_4-ciphertext", "message_4 with a bit of its tag flipped", 4, flip(f4, len(f4) - 1), as_initiator_4)

    # message_3 that decrypts, but names a point of order 8 as the initiator's address. X25519 on
    # any small-order point gives all zeros, because its scalars are multiples of 8, so an
    # implementation that skipped the address check would still have to refuse it there.
    st_r = r_state()
    k_3 = kdf(st_r["prk_3e2m"], 3, st_r["th_3"], KEY_LEN)
    iv_3 = kdf(st_r["prk_3e2m"], 4, st_r["th_3"], IV_LEN)
    bad = encode(small_order_points()[-1])
    pt_3 = id_cred_i(bad) + cbor(bytes(MAC_LEN))
    f3_bad = frame(3, st_r["ctag"][3], cbor(seal(k_3, iv_3, st_r["th_3"], pt_3)))
    reject("message_3-address", "message_3 that decrypts, naming a small-order address", 3, f3_bad, as_responder_3)

    # The initiator's own key, claiming its address plus a point of order 8. X25519 gives the same
    # G_IY for both, so the MAC is right: only the address check refuses it.
    g_iy = X25519.dh(det("y 0"), x25519_public(address(i_seed)))
    prk_4e3m = extract(kdf(st_r["prk_3e2m"], 5, st_r["th_3"], HASH_LEN), g_iy)
    mac_3 = kdf(prk_4e3m, 6, id_cred_i(mixed) + cbor(st_r["th_3"]) + cred(mixed), MAC_LEN)
    pt_3 = id_cred_i(mixed) + cbor(mac_3)
    f3_mixed = frame(3, st_r["ctag"][3], cbor(seal(k_3, iv_3, st_r["th_3"], pt_3)))
    assert responder_receive_3(r_state(), f3_mixed, check_address=False) is not None
    reject("message_3-mixed-order", "message_3 from the initiator's own key, claiming its address plus a "
           "point of order 8: the MAC verifies, and only the address check refuses it", 3, f3_mixed, as_responder_3)

    return {
        "description": (
            "First contact, draft 0 (draft/first-contact.md). For each address, an implementation "
            "given seed MUST derive address, x25519_private and x25519_public. Each rejected address "
            "MUST be refused: as a target to contact, and in a message_3. For each handshake, an "
            "initiator given initiator_seed, the address of responder_seed, initiator_ephemeral and "
            "c_i MUST send frames[0], MUST send frames[2] on receiving frames[1], and on receiving "
            "frames[3] MUST derive session_secret; a responder given responder_seed, "
            "responder_ephemeral and c_r MUST send frames[1] on receiving frames[0], and on "
            "receiving frames[2] MUST send frames[3], learn the initiator's address and derive "
            "session_secret. Setting the ephemeral keys and connection identifiers is a test hook. "
            "A node given a not_for_me frame MUST NOT reply. Each rejected frame replaces message "
            "number `message` of the named handshake, and its receiver, otherwise in the state that "
            "handshake leaves it in, MUST reject it: send nothing and derive no session. hop and "
            "label are 0 throughout. Values are hex."
        ),
        "generator": "vectors/tools/first_contact.py",
        "exporter_label": EXPORTER_LABEL,
        "addresses": addresses,
        "rejected_addresses": rejected_addresses,
        "handshakes": [case0, case1, case2],
        "not_for_me": not_for_me,
        "rejected": rejected,
    }


def render() -> str:
    return json.dumps(build(), indent=2) + "\n"


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    text = render()
    if cmd == "generate":
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT}")
        return 0
    if cmd == "check":
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} differs from what {Path(__file__).name} computes", file=sys.stderr)
            return 1
        print("ok")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
