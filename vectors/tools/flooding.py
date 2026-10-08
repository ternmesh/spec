#!/usr/bin/env python3
"""Generates and checks the test vectors for flooded frames (draft/flooding.md).

    python3 vectors/tools/flooding.py generate   # rewrite vectors/flooding.json
    python3 vectors/tools/flooding.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Airtimes come from phy.py, beside this file.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phy  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "flooding.json"

HDR_GROUP = 0x60
HEAD = 3
GROUP_MIN = 27
FLOOD_HOPS = 5
FLOOD_SPARSE = 8
FLOOD_WAIT = 8
FLOOD_COPIES = 2
SEEN_FOR_NS = 60 * 1_000_000_000
SEEN_ROOM = 128
POWER_MARGIN = 10
FLOOD_OWN_PPM, FLOOD_OWN_WINDOW_S = 5_000, 600
FLOOD_RELAY_PPM, FLOOD_RELAY_WINDOW_S = 30_000, 60


def head(hdr, hops, power):
    return struct.pack(">BBb", hdr, hops, power)


def flooded(frame):
    """Whether a receiver takes a frame as a flooded one."""
    return len(frame) <= 255 and len(frame) >= GROUP_MIN and frame[0] == HDR_GROUP


def frame_id(frame):
    return hashlib.sha256(frame[HEAD:]).digest()[:8]


def passes(relay, relay_neighbours, hops):
    """The hops a node sends a frame on with, having not seen it before, or None for not at
    all. A bridge spends no hop."""
    hops = min(hops, FLOOD_HOPS)
    if not relay or hops == 0:
        return None
    if relay_neighbours <= FLOOD_SPARSE:
        return hops
    return hops - 1 if hops > 1 else None


def longest_wait(sf, bw_hz, length):
    return FLOOD_WAIT * phy.airtime_ns(sf, bw_hz, length)


def power(every, floors, lowest, full):
    """What a flooded frame goes at: as a frame for every neighbour, and loud enough for every
    relay neighbour a selected route goes through. Floors are in sixteenths of a dBm."""
    if any(f is None for f in floors):
        return full
    need = max([every] + [-(-(f + 16 * POWER_MARGIN) // 16) for f in floors])
    return max(lowest, min(full, need))


class Seen:
    """The ids a node holds as seen: each for SEEN_FOR at least, unless SEEN_ROOM came after."""

    def __init__(self):
        self.took = []  # (at, id), oldest first

    def take(self, at, i):
        self.took.append((at, i))

    def must(self, at, i):
        for k, (t, j) in enumerate(self.took):
            if j == i and t <= at < t + SEEN_FOR_NS:
                after = sum(1 for (u, _) in self.took[k + 1:] if u <= at)
                if after < SEEN_ROOM:
                    return True
        return False


class Bucket:
    """A token bucket in millionths of a nanosecond of airtime, so that nothing is rounded."""

    def __init__(self, ppm, window_s, sf, bw_hz):
        self.ppm = ppm
        self.room = max(ppm * window_s * 1_000_000_000, phy.airtime_ns(sf, bw_hz, 255) * 1_000_000)
        self.level, self.at = self.room, 0

    def pays(self, at, airtime_ns):
        self.level = min(self.room, self.level + (at - self.at) * self.ppm)
        self.at = at
        cost = airtime_ns * 1_000_000
        if self.level < cost:
            return False
        self.level -= cost
        return True


def self_check():
    f = head(0x60, 5, -3) + bytes(range(24))
    assert f[:3].hex() == "6005fd" and flooded(f) and not flooded(f[:-1])
    assert frame_id(f) == frame_id(head(0x60, 2, 14) + bytes(range(24)))
    # Four relays in a crowd pass a frame on along any path: 5, 4, 3, 2, and the one that hears 1
    # does not.
    assert [passes(True, 9, h) for h in (5, 4, 3, 2, 1, 0)] == [4, 3, 2, 1, None, None]
    assert [passes(True, 8, h) for h in (5, 1, 0)] == [5, 1, None] and passes(False, 0, 5) is None
    assert passes(True, 9, 200) == 4
    # A 67-byte frame at SF9 and 500 kHz, by phy.py, which checks its own arithmetic.
    assert longest_wait(9, 500_000, 67) == 8 * phy.airtime_ns(9, 500_000, 67)
    # A floor of -3.5 dBm and the margin is 6.5, rounded up to 7; louder than announces at 2.
    assert power(2, [-56], -9, 22) == 7 and power(2, [], -9, 22) == 2
    assert power(2, [-56, None], -9, 22) == 22 and power(2, [300], -9, 22) == 22
    # 0.5% of ten minutes is 3 s of airtime: nine frames of 320.768 ms, and not a tenth.
    b = Bucket(FLOOD_OWN_PPM, FLOOD_OWN_WINDOW_S, 9, 500_000)
    assert [b.pays(0, 320_768_000) for _ in range(10)] == [True] * 9 + [False]
    # What is left is 113.088 ms; the rest of a frame, 207.68 ms, takes 41.536 s to come.
    assert not b.pays(41_535_999_999, 320_768_000) and b.pays(41_536_000_000, 320_768_000)


def build():
    self_check()
    body = bytes(range(0x30, 0x30 + 24))
    heads = []
    for hdr, hops, pw, rest in [
        (0x60, 5, 22, body),
        (0x60, 1, -9, bytes(range(0x80, 0x80 + 40))),
        (0x60, 0, 0, bytes(252)),
    ]:
        f = head(hdr, hops, pw) + rest
        assert flooded(f)
        heads.append({"hdr": hdr, "hops": hops, "power": pw, "rest": rest.hex(),
                      "id": frame_id(f).hex(), "frame": f.hex()})

    good = head(0x60, 5, 14) + body
    rejected = []
    for name, f in [
        ("short", good[:-1]),
        ("a-message", bytes([0x48]) + good[1:]),
        ("an-acknowledgement", bytes([0x50]) + good[1:]),
        ("an-announce", bytes([0x59]) + good[1:]),
        ("a-flag-set", bytes([0x61]) + good[1:]),
        ("empty", b""),
    ]:
        assert not flooded(f)
        rejected.append({"name": name, "frame": f.hex()})

    other = bytearray(good)
    other[-1] ^= 1
    first = bytearray(good)
    first[3] ^= 0x80
    same = []
    for name, a, b in [
        ("passed-on", good, head(0x60, 4, -2) + body),
        ("itself", good, good),
        ("last-byte", good, bytes(other)),
        ("first-byte-after-the-head", good, bytes(first)),
        ("longer", good, good + b"\x00"),
    ]:
        same.append({"name": name, "a": a.hex(), "b": b.hex(), "same": frame_id(a) == frame_id(b)})

    passed = []
    for role, n in [("relay", 9), ("relay", 8), ("relay", 0), ("relay", 40), ("leaf", 3)]:
        for hops in (5, 4, 2, 1, 0, 6, 255):
            passed.append({"role": role, "relay_neighbours": n, "hops": hops,
                           "sends": passes(role == "relay", n, hops)})

    copies = [{"received": n, "drops": n >= FLOOD_COPIES} for n in (1, 2, 3)]

    waits = []
    for _, _, bw, sf, _, _, _ in phy.PROFILES:
        for length in (27, 67, 255):
            waits.append({"spreading_factor": sf, "bandwidth_hz": bw, "length": length,
                          "airtime_ns": phy.airtime_ns(sf, bw, length),
                          "longest_ns": longest_wait(sf, bw, length)})

    powers = []
    for every, floors, lowest, full in [
        (2, [], -9, 22),
        (2, [-56], -9, 22),
        (2, [-56, 40, -200], -9, 22),
        (12, [-56], -9, 22),
        (2, [-56, None], -9, 22),
        (22, [], -9, 22),
        (-9, [-400], -9, 22),
        (2, [300], -9, 22),
        (2, [16], -9, 22),
        (2, [17], -9, 22),
    ]:
        powers.append({"every": every, "floors_sixteenths": floors, "lowest": lowest, "full": full,
                       "power": power(every, floors, lowest, full)})

    s = 1_000_000_000
    seen = []
    one = Seen()
    one.take(0, "a")
    seen.append({
        "name": "for-a-minute",
        "takes": [{"at_ns": 0, "id": "a"}],
        "asks": [{"at_ns": t, "id": i, "seen": one.must(t, i)}
                 for t, i in [(0, "a"), (59 * s, "a"), (60 * s - 1, "a"), (0, "b")]],
    })
    many = Seen()
    takes = [(0, "a")] + [(s + k, f"n{k}") for k in range(SEEN_ROOM)]
    for t, i in takes:
        many.take(t, i)
    seen.append({
        "name": "room",
        "note": "128 others taken since: the first may be forgotten, and the second not yet",
        "takes": [{"at_ns": t, "id": i} for t, i in takes],
        "asks": [{"at_ns": t, "id": i, "seen": many.must(t, i)}
                 for t, i in [(s + SEEN_ROOM - 2, "a"), (2 * s, "n0"), (2 * s, "n127")]],
    })
    assert [a["seen"] for a in seen[0]["asks"]] == [True, True, True, False]
    assert [a["seen"] for a in seen[1]["asks"]] == [True, True, True]

    allowances = []
    for name, ppm, window, (_, _, bw, sf, _, _, _), offers in [
        ("own", FLOOD_OWN_PPM, FLOOD_OWN_WINDOW_S, phy.PROFILES[0],
         [(0, 255)] * 10 + [(41_535_999_999, 255), (41_536_000_000, 255), (3600 * s, 67)]),
        ("own-short", FLOOD_OWN_PPM, FLOOD_OWN_WINDOW_S, phy.PROFILES[1],
         [(k * s, 67) for k in range(30)]),
        ("relay", FLOOD_RELAY_PPM, FLOOD_RELAY_WINDOW_S, phy.PROFILES[0],
         [(k * 100_000_000, 120) for k in range(16)] + [(10 * s, 255), (10 * s, 255), (10 * s, 27)]),
        ("relay-eu", FLOOD_RELAY_PPM, FLOOD_RELAY_WINDOW_S, phy.PROFILES[1],
         [(0, 255)] * 6 + [(5 * s, 67), (5 * s, 67), (60 * s, 255)]),
    ]:
        b = Bucket(ppm, window, sf, bw)
        frames = []
        for at, length in offers:
            air = phy.airtime_ns(sf, bw, length)
            frames.append({"at_ns": at, "airtime_ns": air, "pays": b.pays(at, air)})
        assert any(f["pays"] for f in frames) and not all(f["pays"] for f in frames), name
        allowances.append({"name": name, "share_ppm": ppm, "window_s": window,
                           "spreading_factor": sf, "bandwidth_hz": bw, "frames": frames})

    return {
        "description": "Frames for every node, draft 0 (draft/flooding.md). Frames, ids and what "
        "follows a head (rest) are hex; power is signed. A frame's id is the first eight bytes of "
        "the SHA-256 of everything after its three-byte head. In passes, a node of that role with "
        "that many relay neighbours receives a frame it has not seen with those hops, and sends "
        "it on with sends as its hops, or does not, for null. In copies, received counts every "
        "copy a relay waiting to pass a frame on has received, the first included. In waits, "
        "airtime_ns is the frame's time on the air with the profiles' preamble and coding rate "
        "(vectors/phy.json) and longest_ns the longest a relay waits before passing it on. In "
        "powers, every is what Routes gives for a frame for every neighbour, in dBm, and "
        "floors_sixteenths the floors, in sixteenths of a dBm, of the neighbours the node's "
        "selected routes go through that are relays, null for one not known. In seen, ids are names, "
        "taken as seen at the times given, and each ask is true where the node must still hold "
        "the id as seen; an id never taken is not seen. In allowances, a bucket that fills at "
        "share_ppm millionths of the node's time and holds window_s seconds of that, or one "
        "255-byte frame if that is more, is full at time 0; each frame is offered at at_ns, and "
        "is sent and charged if the bucket pays.",
        "generator": "vectors/tools/flooding.py",
        "heads": heads,
        "rejected": rejected,
        "same": same,
        "passes": passed,
        "copies": copies,
        "waits": waits,
        "powers": powers,
        "seen": seen,
        "allowances": allowances,
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
