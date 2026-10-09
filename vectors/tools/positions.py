#!/usr/bin/env python3
"""Generates and checks the position test vectors (draft/positions.md).

    python3 vectors/tools/positions.py generate   # rewrite vectors/positions.json
    python3 vectors/tools/positions.py check      # fail if the file differs from what this computes

Needs the `cryptography` package, for the frames that carry a position. Its primitives are
unicast.py's and groups.py's, beside this file; unicast.py checks them against RFC 5869 and
RFC 3610 before anything is computed. Time on air is phy.py's. The grid is integer arithmetic
throughout, and is checked first against cells worked by hand.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import groups  # noqa: E402
import phy  # noqa: E402
import unicast  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "positions.json"

KIND_POSITION = 0x02
PRECISION_MAX = 24
ALTITUDE, ACCURACY, AGE = 0x01, 0x02, 0x04  # the flags in form's low three bits
NO_ALTITUDE = -32768

LAT_SPAN = 1_800_000_000  # 180 degrees, in units of 10^-7 degree
LON_SPAN = 3_600_000_000  # 360 degrees
LAT_MIN = -900_000_000
LON_MIN = -1_800_000_000

HDR_GROUP_NODE = 0x61  # a group frame (0x60) with the node flag set
HDR_UNICAST_NODE = unicast.HDR_NODE  # 0x49

# Parameters of draft/positions.md.
POSITION_MIN = 60
POSITION_GROUP_MIN = 300
POSITION_REFRESH = 3600
POSITION_STALE = 3600


def where_bytes(precision):
    """How many bytes a cell of this precision takes: 2b - 1 bits, rounded up to whole bytes."""
    return (2 * precision - 1 + 7) // 8 if precision else 0


def cell(lat, lon, b):
    """The cell a point is in, at precision b: (row, column). lat and lon in 10^-7 degree."""
    assert 1 <= b <= PRECISION_MAX
    assert -900_000_000 <= lat <= 900_000_000 and -1_800_000_000 <= lon <= 1_800_000_000
    row = min(((lat - LAT_MIN) << (b - 1)) // LAT_SPAN, (1 << (b - 1)) - 1)
    col = (((lon - LON_MIN) << b) // LON_SPAN) % (1 << b)
    return row, col


def centre(row, col, b):
    """The centre of a cell, in 10^-7 degree, rounded down."""
    return ((2 * row + 1) * LAT_SPAN >> b) + LAT_MIN, ((2 * col + 1) * LON_SPAN >> (b + 1)) + LON_MIN


def corner(row, col, b):
    """The cell's south-west corner, exactly: where it begins in each direction."""
    return (row * LAT_SPAN >> (b - 1)) + LAT_MIN, (col * LON_SPAN >> b) + LON_MIN


def pack(row, col, b):
    bits = 2 * b - 1
    n = where_bytes(b)
    return ((row << b | col) << (8 * n - bits)).to_bytes(n, "big")


def unpack(where, b):
    """(row, column), or None if a padding bit is set."""
    bits, n = 2 * b - 1, where_bytes(b)
    v = int.from_bytes(where, "big")
    pad = 8 * n - bits
    if v & ((1 << pad) - 1):
        return None
    v >>= pad
    return v >> b, v & ((1 << b) - 1)


def age_byte(seconds):
    """A fix's age as one byte: seconds below a minute, then whole minutes, then 255."""
    assert seconds >= 0
    if seconds < 60:
        return seconds
    return min(59 + seconds // 60, 255)


def age_seconds(byte):
    """The least age a byte can stand for, in seconds."""
    return byte if byte < 60 else (byte - 59) * 60


def encode(precision, lat=None, lon=None, altitude=None, accuracy=None, age=None):
    """The plaintext of a position: kind, form, the cell, then whichever optional fields."""
    if precision == 0:
        return bytes([KIND_POSITION, 0])
    flags = (ALTITUDE if altitude is not None else 0) | (ACCURACY if accuracy is not None else 0) | (
        AGE if age is not None else 0)
    out = bytes([KIND_POSITION, precision << 3 | flags]) + pack(*cell(lat, lon, precision), precision)
    if altitude is not None:
        assert -32767 <= altitude <= 32767
        out += struct.pack(">h", altitude)
    if accuracy is not None:
        out += bytes([min(max(accuracy, 1), 255)])
    if age is not None:
        out += bytes([age_byte(age)])
    return out


def decode(p):
    """What a receiver reads from the plaintext of a message for the node: a dict, or the reason
    it is ignored. Bytes after the fields are read past: that is how a later draft adds one."""
    if len(p) < 2:
        return "shorter than a kind and a form"
    if p[0] != KIND_POSITION:
        return "another kind"
    b, flags = p[1] >> 3, p[1] & 0x07
    if b > PRECISION_MAX:
        return "a precision above 24"
    if b == 0:
        if flags:
            return "a stopped position with fields"
        return {"precision": 0}
    n = where_bytes(b)
    need = 2 + n + (2 if flags & ALTITUDE else 0) + (1 if flags & ACCURACY else 0) + (
        1 if flags & AGE else 0)
    if len(p) < need:
        return "shorter than its fields"
    got = unpack(p[2 : 2 + n], b)
    if got is None:
        return "a padding bit set"
    row, col = got
    c_lat, c_lon = centre(row, col, b)
    s_lat, s_lon = corner(row, col, b)
    out = {"precision": b, "row": row, "column": col, "latitude": c_lat, "longitude": c_lon,
           "south": s_lat, "west": s_lon}
    at = 2 + n
    if flags & ALTITUDE:
        alt = struct.unpack(">h", p[at : at + 2])[0]
        if alt == NO_ALTITUDE:
            return "altitude -32768"
        out["altitude"] = alt
        at += 2
    if flags & ACCURACY:
        if p[at] == 0:
            return "accuracy 0"
        out["accuracy"] = p[at]
        at += 1
    if flags & AGE:
        out["age"] = age_seconds(p[at])
        at += 1
    return out


def seal_group(g, n, sender, content, flood=groups.FLOOD):
    """A group frame with the node flag set: groups.md's frame, with hdr 0x61."""
    t = groups.gtag(g, n)
    plaintext = struct.pack(">I", sender) + content
    ct = AESCCM(groups.group_key(g), tag_length=8).encrypt(
        bytes(5) + n, plaintext, bytes([HDR_GROUP_NODE]) + n + t)
    return struct.pack(">BBb", HDR_GROUP_NODE, flood["hops"], flood["power"]) + n + t + ct


def open_group(g, frame):
    n, t = frame[3:11], frame[11:15]
    if frame[0] != HDR_GROUP_NODE or t != groups.gtag(g, n):
        return None
    p = AESCCM(groups.group_key(g), tag_length=8).decrypt(bytes(5) + n, frame[15:], frame[0:1] + n + t)
    return struct.unpack(">I", p[:4])[0], p[4:]


class Receiver:
    """What a node holds from the other end of one session: the position, and the counter of
    the last message it took a position from, which it keeps after the position is forgotten."""

    def __init__(self):
        self.held, self.last = None, None

    def receive(self, contact, counter, plaintext):
        got = decode(plaintext)
        if not contact or isinstance(got, str):
            return self.held
        if self.last is not None and counter < self.last:
            return self.held  # older than one already taken: overtaken on the way
        self.last = counter
        self.held = None if got["precision"] == 0 else got
        return self.held


def due(interval, last_at, changed, age, now):
    """Whether a position may go to a destination now. last_at is when the last position to it
    went on the air, None if none has since sharing began; changed, whether the position it would
    send differs from that one; age, how old the fix is."""
    if age > POSITION_STALE:
        return False
    if last_at is None:
        return True
    if now - last_at < interval:
        return False
    return changed or now - last_at >= POSITION_REFRESH


def self_check():
    unicast.self_test()
    # Cells worked by hand. At precision 1 there is no row bit, and the column is the
    # hemisphere east or west of 180 degrees from Greenwich: west of Greenwich is column 0.
    assert cell(0, -1, 1) == (0, 0) and cell(0, 0, 1) == (0, 1)
    assert pack(0, 1, 1) == b"\x80"
    # Precision 2: rows of 90 degrees, columns of 90 degrees. 45 N, 45 E is row 1, column 2.
    assert cell(450_000_000, 450_000_000, 2) == (1, 2)
    assert centre(1, 2, 2) == (450_000_000, 450_000_000)
    assert pack(1, 2, 2) == bytes([0b11000000])  # row 1 (one bit), column 10
    # The north pole is in the top row, and 180 E is 180 W: the same meridian.
    assert cell(900_000_000, 1_800_000_000, 8) == (127, 0)
    assert cell(-900_000_000, -1_800_000_000, 8) == (0, 0)
    # Each byte of where, four bits more of each coordinate.
    assert [where_bytes(b) for b in (4, 8, 12, 16, 20, 24)] == [1, 2, 3, 4, 5, 6]
    assert age_byte(59) == 59 and age_byte(60) == 60 and age_byte(119) == 60 and age_byte(120) == 61
    assert age_byte(195 * 60) == 254 and age_byte(196 * 60) == 255 and age_seconds(255) == 196 * 60
    # Nothing past 2^63, so a node can do the grid in 64-bit integers.
    assert (LON_SPAN << PRECISION_MAX) < 2**63 and ((2 * (1 << 24) + 1) * LON_SPAN) < 2**63


# A few places, in 10^-7 degree: a summit, a harbour, a town south of the equator and west of
# Greenwich, and one on the antimeridian.
SUMMIT = (458_325_000, 68_644_000)  # 45.8325 N, 6.8644 E
HARBOUR = (603_946_000, 52_878_000)  # 60.3946 N, 5.2878 E
SOUTH_WEST = (-336_183_000, -704_517_000)  # 33.6183 S, 70.4517 W
DATELINE = (-170_000_000, 1_800_000_000)  # 17 S, 180


def build():
    self_check()

    grid = []
    for name, (lat, lon), bs in [
        ("summit", SUMMIT, (1, 2, 8, 12, 16, 18, 20, 24)),
        ("harbour", HARBOUR, (12, 16, 20, 24)),
        ("south-west", SOUTH_WEST, (8, 12, 16, 20, 24)),
        ("dateline", DATELINE, (12, 24)),
        ("north-pole", (900_000_000, 0), (1, 12, 24)),
        ("south-pole", (-900_000_000, 0), (12, 24)),
        ("greenwich-equator", (0, 0), (1, 2, 24)),
        ("just-west", (0, -1), (24,)),
        ("an-edge", corner(*cell(*SUMMIT, 16), 16), (16,)),
        ("just-below-an-edge", (corner(*cell(*SUMMIT, 16), 16)[0] - 1, SUMMIT[1]), (16,)),
    ]:
        for b in bs:
            row, col = cell(lat, lon, b)
            c = centre(row, col, b)
            s = corner(row, col, b)
            assert unpack(pack(row, col, b), b) == (row, col)
            assert s[0] <= lat or row == (1 << (b - 1)) - 1
            grid.append({"name": name, "latitude": lat, "longitude": lon, "precision": b,
                         "row": row, "column": col, "where": pack(row, col, b).hex(),
                         "centre_latitude": c[0], "centre_longitude": c[1],
                         "south": s[0], "west": s[1]})

    positions = []
    for name, note, kw in [
        ("town", "precision 12, nothing else: five bytes", dict(precision=12, lat=SUMMIT[0], lon=SUMMIT[1])),
        ("neighbourhood", "precision 16", dict(precision=16, lat=SUMMIT[0], lon=SUMMIT[1])),
        ("street", "precision 20, with its age", dict(precision=20, lat=HARBOUR[0], lon=HARBOUR[1], age=95)),
        ("exact", "precision 24, with altitude, accuracy and age",
         dict(precision=24, lat=SUMMIT[0], lon=SUMMIT[1], altitude=4806, accuracy=4, age=12)),
        ("exact-south-west", "precision 24, altitude only, below the ellipsoid",
         dict(precision=24, lat=SOUTH_WEST[0], lon=SOUTH_WEST[1], altitude=-12)),
        ("accuracy-only", "precision 22, accuracy 255: 255 m or worse",
         dict(precision=22, lat=HARBOUR[0], lon=HARBOUR[1], accuracy=300)),
        ("old", "an age past 195 minutes", dict(precision=18, lat=DATELINE[0], lon=DATELINE[1], age=4 * 3600)),
        ("hemisphere", "precision 1: which side of Greenwich", dict(precision=1, lat=SUMMIT[0], lon=SUMMIT[1])),
        ("stopped", "precision 0: the sender has stopped sharing", dict(precision=0)),
    ]:
        p = encode(**kw)
        got = decode(p)
        assert isinstance(got, dict)
        positions.append({"name": name, "note": note, **{
            {"lat": "latitude", "lon": "longitude", "age": "age_seconds"}.get(k, k): v
            for k, v in kw.items()}, "plaintext": p.hex(), "read": got})

    extended = []
    for p in (encode(16, *SUMMIT) + b"\xaa\xbb", encode(0) + b"\x01"):
        got = decode(p)
        assert isinstance(got, dict)
        extended.append({"plaintext": p.hex(), "read": got})

    exact = encode(24, *SUMMIT, altitude=4806, accuracy=4, age=12)
    town = encode(12, *SUMMIT)
    ignored = []
    for p in [
        b"",
        b"\x02",
        b"\x01" + town[1:],  # an invite's kind
        b"\x03" + town[1:],  # a kind not defined
        bytes([2, 25 << 3]) + bytes(7),  # precision 25
        bytes([2, 31 << 3 | 7]) + bytes(12),
        b"\x02\x01",  # stopped, with altitude
        b"\x02\x04\x05",  # stopped, with an age
        town[:-1],  # the cell cut short
        exact[:-1],  # the age missing
        exact[:-4],  # the altitude cut
        town[:-1] + bytes([town[-1] | 0x01]),  # a padding bit set
        bytes([2, 24 << 3 | ALTITUDE]) + pack(*cell(*SUMMIT, 24), 24) + b"\x80\x00",
        bytes([2, 24 << 3 | ACCURACY]) + pack(*cell(*SUMMIT, 24), 24) + b"\x00",
    ]:
        why = decode(p)
        assert isinstance(why, str), p.hex()
        ignored.append({"why": why, "plaintext": p.hex()})
    assert len(ignored) == 14

    ages = [{"seconds": s, "byte": age_byte(s), "read_seconds": age_seconds(age_byte(s))}
            for s in (0, 1, 59, 60, 61, 119, 120, 600, 3599, 3600, 195 * 60, 196 * 60, 86_400)]

    sizes = []
    for b in (0, 1, 4, 8, 12, 16, 18, 20, 22, 24):
        rows = []
        for fields, kw in [("", {}), ("altitude, accuracy, age", dict(altitude=0, accuracy=1, age=0))]:
            if b == 0 and fields:
                continue
            p = encode(b, *SUMMIT, **kw) if b else encode(0)
            u, g = unicast.OVERHEAD + len(p), groups.MIN_FRAME + len(p)
            rows.append({"fields": fields, "plaintext": len(p), "unicast_frame": u, "group_frame": g,
                         "airtime_ns": {name: {"unicast": phy.airtime_ns(sf, bw, u),
                                               "group": phy.airtime_ns(sf, bw, g)}
                                        for name, _, bw, sf, *_ in phy.PROFILES}})
        sizes.append({"precision": b, "where_bytes": where_bytes(b),
                      "cell_degrees": f"360/2^{b}" if b else None, "lengths": rows})

    # The frames that carry a position. The unicast one is the session of unicast-security.json's
    # first case; the group one, groups.json's first group.
    s1 = bytes(range(32))
    uni = unicast.seal(s1, 1, 5, exact, hdr=HDR_UNICAST_NODE)
    assert unicast.open_frame(s1, 1, 5, uni) == exact
    g1 = bytes(range(16))
    nonce = bytes.fromhex("5050505050505050")
    alice = 0x1D2E3F40
    grp = seal_group(g1, nonce, alice, town)
    assert open_group(g1, grp) == (alice, town)
    # A member that knows only groups.md's frame does not take it: its header is authenticated.
    assert groups.open_frame(g1, 0x0A0B0C0D, grp) is None
    frames = [
        {"name": "to-a-contact", "note": "a secured unicast frame with the node flag set",
         "session_secret": s1.hex(), "direction": 1, "counter": 5, "hdr": HDR_UNICAST_NODE,
         **unicast.ROUTE, "plaintext": exact.hex(), "frame": uni.hex()},
        {"name": "to-a-group", "note": "a group frame with the node flag set",
         "group_secret": g1.hex(), "nonce": nonce.hex(), "from": alice, "hdr": HDR_GROUP_NODE,
         **groups.FLOOD, "content": town.hex(), "frame": grp.hex()},
    ]

    receiving = []
    for name, note, deliveries in [
        ("overtaken", "an older position after a newer is ignored", [
            (True, 5, encode(24, *SUMMIT)), (True, 3, encode(12, *HARBOUR)),
            (True, 6, encode(16, *HARBOUR))]),
        ("after-stopped", "a stopped position overtakes an older one, which is ignored when it "
         "comes: the counter is kept though the position is forgotten", [
            (True, 5, encode(24, *SUMMIT)), (True, 7, encode(0)), (True, 6, encode(20, *SUMMIT)),
            (True, 8, encode(12, *SUMMIT))]),
        ("ignored-keeps-nothing", "a plaintext that is ignored moves no counter", [
            (True, 9, encode(12, *SUMMIT)[:-1]), (True, 4, encode(12, *SUMMIT))]),
        ("not-a-contact", "a position from an address that is not a contact is ignored", [
            (False, 0, encode(12, *SUMMIT)), (False, 1, encode(0))]),
    ]:
        r = Receiver()
        out = []
        for contact, counter, p in deliveries:
            out.append({"contact": contact, "counter": counter, "plaintext": p.hex(),
                        "holds": r.receive(contact, counter, p)})
        receiving.append({"name": name, "note": note, "deliveries": out})
    assert [d["holds"] for d in receiving[1]["deliveries"]][1:3] == [None, None]
    assert receiving[0]["deliveries"][1]["holds"]["precision"] == 24

    schedule = []
    for note, interval, last_at, changed, age, now in [
        ("the first since sharing began", 900, None, True, 0, 1000),
        ("the first, even unchanged", 900, None, False, 0, 1000),
        ("too soon after the last", 900, 1000, True, 0, 1899),
        ("the interval passed, and it moved", 900, 1000, True, 0, 1900),
        ("the interval passed, and it did not move", 900, 1000, False, 0, 1900),
        ("not moved, refreshed after POSITION_REFRESH", 900, 1000, False, 0, 4600),
        ("not moved, a second short of it", 900, 1000, False, 0, 4599),
        ("an interval longer than the refresh", 7200, 1000, False, 0, 8200),
        ("a fix too old", 900, None, True, 3601, 1000),
        ("a fix exactly POSITION_STALE old", 900, None, True, 3600, 1000),
        ("a group's least interval", POSITION_GROUP_MIN, 1000, True, 30, 1300),
        ("a contact's least interval", POSITION_MIN, 1000, True, 30, 1059),
    ]:
        schedule.append({"note": note, "interval": interval, "last_at": last_at, "changed": changed,
                         "age": age, "now": now, "due": due(interval, last_at, changed, age, now)})

    return {
        "description": "Positions, draft 0 (draft/positions.md). Latitudes and longitudes are "
        "integers in units of 10^-7 degree, north and east positive; plaintexts, where, frames, "
        "secrets and nonces are hex; times are seconds. In grid, row and column are the cell of "
        "the point at precision, where is how they go on the air, and centre_latitude, "
        "centre_longitude, south and west are the cell's centre, rounded down, and its "
        "south-west corner. In positions, plaintext is that of a message for the node made from "
        "the other fields (accuracy as the sender's estimate in metres, age_seconds as the fix's "
        "age), and read is what a receiver takes from it, age in seconds as the least the byte "
        "stands for. In extended, bytes after the fields are read past. A receiver ignores each "
        "plaintext of ignored. In ages, byte is the age field for seconds, and read_seconds what "
        "it is read as. In sizes, the lengths in bytes of a position at each precision, without "
        "its optional fields and with all three, and of the unicast and group frames that carry "
        "it, with their time on air at each profile of draft/phy.md. In frames, a position as "
        "each frame carries it; the unicast frame's route is hops, power, next and destination. "
        "In receiving, each case is one session, new, and holds is what read gives "
        "for the position the node holds from its other end after each delivery, null for none. "
        "In schedule, due is whether a position may go to a destination, given interval, when "
        "the last went (last_at, null for none since sharing began), whether the position "
        "changed since, the fix's age and the time now.",
        "generator": "vectors/tools/positions.py",
        "grid": grid,
        "positions": positions,
        "extended": extended,
        "ignored": ignored,
        "ages": ages,
        "sizes": sizes,
        "frames": frames,
        "receiving": receiving,
        "schedule": schedule,
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
