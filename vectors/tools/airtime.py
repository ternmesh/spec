#!/usr/bin/env python3
"""Generates and checks the test vectors for the airtime budget (draft/airtime.md).

    python3 vectors/tools/airtime.py generate   # rewrite vectors/airtime.json
    python3 vectors/tools/airtime.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Airtimes and the profiles come from phy.py, and the
flood allowances from flooding.py, beside this file. Before computing anything it checks its
arithmetic against values worked by hand.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flooding  # noqa: E402
import phy  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "airtime.json"

NS = 1_000_000_000
BUDGET_OWN_PPM, BUDGET_OWN_WINDOW_S = 10_000, 600
BUDGET_RELAY_PPM, BUDGET_RELAY_WINDOW_S = 80_000, 60
# Routes' cap (draft/routing.md): CAP, of which REQUEST_SHARE for requests; and a relay's learning
# allowance, LEARN_SHARE of the announces' share.
CAP_PPM = 5_000
LEARN_PPM = CAP_PPM * 3 // 4 // 2
WAIT_MAX = 0xFFFF

HDR_MESSAGE, HDR_MESSAGE_NODE, HDR_ACK = 0x48, 0x49, 0x50
HDR_CONTACT = (0x51, 0x52, 0x53, 0x54)
HDR_ROUTING = (0x59, 0x5A, 0x5B, 0x5C)  # announce, request, solicit, answer
HDR_FLOODED = (0x60, 0x61, 0x68)

US915, EU868 = phy.PROFILES[0], phy.PROFILES[1]


def part(hdr, own):
    """The part of the budget that pays for a frame: own, relayed, or routing (Routes' cap)."""
    if hdr in HDR_ROUTING:
        return "routing"
    assert hdr in (HDR_MESSAGE, HDR_MESSAGE_NODE, HDR_ACK) + HDR_CONTACT + HDR_FLOODED
    return "own" if own else "relayed"


def flood_bucket(hdr, own):
    """Which of Frames for every node's two allowances also pays for it, or None."""
    if hdr not in HDR_FLOODED:
        return None
    return "flood_own" if own else "flood_relay"


def unpaid(hdr, own):
    """What becomes of a frame its buckets do not all pay for: it waits, it is dropped, or, for an
    acknowledgement, it is sent anyway; None where Routes' cap decides."""
    if part(hdr, own) == "routing":
        return None
    if hdr == HDR_ACK:
        return "sent"
    return "waits" if own else "dropped"


def parts(role):
    relay = role == "relay"
    return {
        "role": role,
        "own_ppm": BUDGET_OWN_PPM,
        "own_window_s": BUDGET_OWN_WINDOW_S,
        "relayed_ppm": BUDGET_RELAY_PPM if relay else None,
        "relayed_window_s": BUDGET_RELAY_WINDOW_S if relay else None,
        "routing_ppm": CAP_PPM,
        "learning_ppm": LEARN_PPM if relay else 0,
        "most_ppm": BUDGET_OWN_PPM + (BUDGET_RELAY_PPM + LEARN_PPM if relay else 0) + CAP_PPM,
    }


class Bucket:
    """A token bucket in millionths of a nanosecond of airtime, so that nothing is rounded: it
    fills at ppm millionths of the node's time and holds window_s of that, or one 255-byte frame
    if that is more. It starts full."""

    def __init__(self, ppm, window_s, sf, bw_hz):
        self.ppm = ppm
        self.room = max(ppm * window_s * NS, phy.airtime_ns(sf, bw_hz, 255) * 1_000_000)
        self.level, self.at = self.room, 0

    def fill(self, at):
        assert at >= self.at
        self.level = min(self.room, self.level + (at - self.at) * self.ppm)
        self.at = at

    def holds(self, at, airtime_ns):
        self.fill(at)
        return self.level >= airtime_ns * 1_000_000

    def charge(self, at, airtime_ns):
        """Takes a frame's airtime, going no lower than empty."""
        self.fill(at)
        self.level = max(0, self.level - airtime_ns * 1_000_000)

    def wait_ns(self, at, need_ns):
        """How long until the bucket holds need_ns of airtime."""
        self.fill(at)
        short = need_ns * 1_000_000 - self.level
        return 0 if short <= 0 else -(-short // self.ppm)


class Node:
    def __init__(self, role, profile):
        _, _, bw, sf, _, _, _ = profile
        self.sf, self.bw = sf, bw
        self.b = {
            "own": Bucket(BUDGET_OWN_PPM, BUDGET_OWN_WINDOW_S, sf, bw),
            "flood_own": Bucket(flooding.FLOOD_OWN_PPM, flooding.FLOOD_OWN_WINDOW_S, sf, bw),
        }
        if role == "relay":
            self.b["relayed"] = Bucket(BUDGET_RELAY_PPM, BUDGET_RELAY_WINDOW_S, sf, bw)
            self.b["flood_relay"] = Bucket(flooding.FLOOD_RELAY_PPM,
                                           flooding.FLOOD_RELAY_WINDOW_S, sf, bw)

    def payers(self, hdr, own):
        names = [part(hdr, own), flood_bucket(hdr, own)]
        return [self.b[n] for n in names if n is not None]

    def offer(self, at, hdr, own, length):
        """Whether the frame is sent now. Every bucket that pays for it is charged at once, or
        none is; an acknowledgement is sent and charged whatever its bucket holds."""
        air = phy.airtime_ns(self.sf, self.bw, length)
        payers = self.payers(hdr, own)
        sent = hdr == HDR_ACK or all(b.holds(at, air) for b in payers)
        if sent:
            for b in payers:
                b.charge(at, air)
        return air, sent

    def waits_s(self, at, waiting):
        """For each of the node's own frames waiting, in order, the seconds until it goes: when
        every bucket that pays for it holds its airtime, and not before the frame ahead of it, each
        frame charged as it goes. Works on copies; the node's buckets are left as they are."""
        b = {name: copy.copy(bucket) for name, bucket in self.b.items()}
        t = at
        out = []
        for hdr, length in waiting:
            air = phy.airtime_ns(self.sf, self.bw, length)
            names = [n for n in (part(hdr, True), flood_bucket(hdr, True)) if n is not None]
            t += max(b[n].wait_ns(t, air) for n in names)
            for n in names:
                b[n].charge(t, air)
            out.append((air, min(WAIT_MAX, -(-(t - at) // NS))))
        return out


def reason(route, session, region_wait_s, budget_wait_s):
    """The reason and the wait a waiting message of the node's own is shown with, as far as this
    section has it: a route, then a session; then whichever of the region's limit and the budget
    lets it go later, the region's if both at once."""
    if not route:
        return 1, 0
    if not session:
        return 2, 0
    assert region_wait_s or budget_wait_s
    if region_wait_s >= budget_wait_s:
        return 3, min(WAIT_MAX, region_wait_s)
    return 4, min(WAIT_MAX, budget_wait_s)


def self_check():
    # The shares a relay may spend, routing's at its largest, are within 10% of the hour.
    assert LEARN_PPM == 1_875 and parts("relay")["most_ppm"] == 96_875
    assert parts("leaf")["most_ppm"] == 15_000
    for name, _, _, _, _, duty, _ in phy.PROFILES:
        assert duty >= parts("relay")["most_ppm"], name
    # 1% of ten minutes is 6 s: fourteen 255-byte frames of 407.808 ms on EU868, and not fifteen.
    n = Node("leaf", EU868)
    assert [n.offer(0, HDR_MESSAGE, True, 255)[1] for _ in range(15)] == [True] * 14 + [False]
    # What is left is 290.688 ms; the rest of a frame, 117.12 ms, takes 11.712 s to come.
    assert not n.offer(11_711_999_999, HDR_MESSAGE, True, 255)[1]
    assert n.offer(11_712_000_000, HDR_MESSAGE, True, 255)[1]
    # Then it is empty: a 19-byte acknowledgement, 59.648 ms, still goes, and leaves no debt; a
    # 255-byte frame then needs 40.7808 s from when it went.
    assert n.waits_s(11_712_000_000, [(HDR_MESSAGE, 255)]) == [(407_808_000, 41)]
    assert n.offer(11_712_000_000, HDR_ACK, True, 19) == (59_648_000, True)
    assert n.b["own"].level == 0
    assert not n.offer(52_492_799_999, HDR_MESSAGE, True, 255)[1]
    assert n.offer(52_492_800_000, HDR_MESSAGE, True, 255)[1]
    # 8% of a minute is 4.8 s: fourteen 255-byte frames of 320.768 ms on US915.
    r = Node("relay", US915)
    assert [r.offer(0, HDR_MESSAGE, False, 255)[1] for _ in range(15)] == [True] * 14 + [False]
    assert r.offer(0, HDR_MESSAGE, True, 255)[1]  # the node's own are apart
    assert reason(False, False, 9, 9) == (1, 0) and reason(True, True, 5, 5) == (3, 5)
    assert reason(True, True, 0, 70_000) == (4, WAIT_MAX)


def build():
    self_check()

    classes = []
    for hdr in (HDR_MESSAGE, HDR_MESSAGE_NODE, HDR_ACK) + HDR_CONTACT + HDR_ROUTING + HDR_FLOODED:
        for own in (True, False):
            classes.append({"hdr": hdr, "own": own, "part": part(hdr, own),
                            "flood_allowance": flood_bucket(hdr, own), "unpaid": unpaid(hdr, own)})

    M, AK, G = HDR_MESSAGE, HDR_ACK, 0x60
    s = NS
    spends = []
    for name, role, profile, offers in [
        # The own part, emptied by a burst, and filling again.
        ("own", "leaf", EU868,
         [(0, M, True, 255)] * 15 + [(11_711_999_999, M, True, 255), (11_712_000_000, M, True, 255),
                                      (11_712_000_000, 0x52, True, 60), (600 * s, M, True, 67)]),
        # An acknowledgement goes when the part is empty, and leaves it empty, not owing.
        ("acknowledgements", "leaf", EU868,
         [(0, M, True, 255)] * 14 + [(0, AK, True, 19)] * 6 + [(0, M, True, 23),
                                                               (40_780_799_999, M, True, 255),
                                                               (40_780_800_000, M, True, 255)]),
        # Group frames of the node's own: the flood allowance, inside the own part, binds first,
        # and a message still goes from what the part has left.
        ("own-floods", "relay", EU868,
         [(0, G, True, 255)] * 8 + [(0, M, True, 255), (0, 0x68, True, 134)]),
        # Frames passed on empty the relayed part; the node's own still go.
        ("relayed", "relay", US915,
         [(0, M, False, 255)] * 15 + [(0, M, True, 255), (0, AK, False, 19),
                                      (825_599_999, M, False, 255),
                                      (825_600_000, M, False, 255)]),
        # Floods passed on: the relay allowance binds first, and a message passed on still goes.
        ("relayed-floods", "relay", US915,
         [(k * 10_000_000, G, False, 255) for k in range(7)] + [(s, 0x51, False, 56),
                                                               (s, 0x61, False, 31)]),
    ]:
        node = Node(role, profile)
        frames = []
        for at, hdr, own, length in offers:
            air, sent = node.offer(at, hdr, own, length)
            frames.append({"at_ns": at, "hdr": hdr, "own": own, "length": length,
                           "airtime_ns": air, "sent": sent})
        assert any(f["sent"] for f in frames) and not all(f["sent"] for f in frames), name
        spends.append({"name": name, "role": role, "profile": profile[0], "frames": frames})
    # A bucket emptied by acknowledgements fills from empty, not from below it.
    assert [f["sent"] for f in spends[1]["frames"][-3:]] == [False, False, True]
    assert [f["sent"] for f in spends[3]["frames"][-2:]] == [False, True]

    estimates = []
    for name, role, profile, spent, at, waiting in [
        ("messages", "leaf", EU868, [(0, M, True, 255)] * 14, 0,
         [(M, 255), (M, 67), (M, 255)]),
        ("later", "leaf", EU868, [(0, M, True, 255)] * 14, 30 * s,
         [(M, 255), (M, 67), (M, 255)]),
        ("group-behind-message", "relay", EU868, [(0, G, True, 255)] * 7 + [(0, M, True, 255)] * 6,
         0, [(M, 255), (G, 255), (G, 120)]),
        ("us915", "relay", US915, [(0, M, True, 255)] * 18, 0, [(M, 23)] * 4),
        ("message-behind-group", "relay", EU868, [(0, G, True, 255)] * 7, 0, [(G, 255), (M, 255)]),
    ]:
        node = Node(role, profile)
        for offer in spent:
            node.offer(*offer)
        rows = node.waits_s(at, waiting)
        estimates.append({
            "name": name, "role": role, "profile": profile[0],
            "spent": [{"at_ns": a, "hdr": h, "own": o, "length": n} for a, h, o, n in spent],
            "at_ns": at,
            "waiting": [{"hdr": h, "length": n, "airtime_ns": air, "wait_s": w}
                        for (h, n), (air, w) in zip(waiting, rows)],
        })
    assert [w["wait_s"] for w in estimates[0]["waiting"]] == [12, 25, 66]
    # A frame never goes before the one ahead of it, even when its own buckets could pay sooner.
    for e in estimates:
        waits = [w["wait_s"] for w in e["waiting"]]
        assert waits == sorted(waits), e["name"]
    assert estimates[-1]["waiting"][1]["wait_s"] == estimates[-1]["waiting"][0]["wait_s"]

    reasons = []
    for route, session, region, budget in [
        (False, True, 0, 30), (True, False, 0, 30), (True, True, 0, 30), (True, True, 30, 0),
        (True, True, 120, 30), (True, True, 30, 120), (True, True, 45, 45),
        (True, True, 0, 70_000),
    ]:
        r, w = reason(route, session, region, budget)
        reasons.append({"route": route, "session": session, "region_wait_s": region,
                        "budget_wait_s": budget, "reason": r, "wait": w})

    return {
        "description": "The airtime budget, draft 0 (draft/airtime.md). Shares are in millionths "
        "of a node's time and windows in seconds; a bucket fills at its share and holds its "
        "window of that, or one 255-byte frame if that is more, and is full at time 0. In parts, "
        "most_ppm is everything a node of that role may spend, routing at its largest, and "
        "relayed_ppm is null for a node that passes nothing on. In classes, part is the part of "
        "the budget that pays for a frame with that hdr, the node's own or passed on; "
        "flood_allowance names the bucket of draft/flooding.md that pays for it too; unpaid is "
        "what becomes of it when they do not all hold its airtime: it waits, it is dropped, or it "
        "is sent and charged, the bucket going no lower than empty; null where Routes' cap "
        "decides. In spends, a node of that role on that profile, every bucket full at time 0, is "
        "offered each frame in order at at_ns; airtime_ns is its time on the air "
        "(vectors/phy.json), and sent says whether it goes then; a frame that goes is charged to "
        "every bucket that pays for it, and one that does not to none. In estimates, the frames "
        "spent go as in spends, and at at_ns the node's own frames waiting go in the order "
        "given; wait_s is how many seconds, rounded up, until it goes: when every bucket that pays "
        "for it holds its airtime, and not before the frame ahead of it, each frame charged to "
        "its buckets as it goes. In "
        "reasons, a message of the node's own waits with or without a route and a session, and "
        "for the region's limit and the budget as long as given, in seconds; reason and wait are "
        "what the companion protocol shows.",
        "generator": "vectors/tools/airtime.py",
        "parts": [parts("relay"), parts("leaf")],
        "classes": classes,
        "spends": spends,
        "estimates": estimates,
        "reasons": reasons,
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
