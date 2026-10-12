#!/usr/bin/env python3
"""Generates and checks the routing test vectors (draft/routing.md).

    python3 vectors/tools/routing.py generate   # rewrite vectors/routing.json
    python3 vectors/tools/routing.py check      # fail if the file differs from what this computes

Needs the Python `cryptography` package, for Ed25519, through cards.py, which checks it against
RFC 8032's test vectors. Time on air and the profiles come from phy.py, beside this file. Every
announce is signed with a seed of first-contact.json, so it is one a node with that address could
send.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phy  # noqa: E402


def _crypto():
    """cards.py, for Ed25519, and first contact's address check: imported only to sign or check
    an announce, so that the generators that import this file for its other rules need nothing
    outside the standard library."""
    import cards
    from first_contact import valid_address

    return cards, valid_address

OUT = Path(__file__).resolve().parent.parent / "routing.json"

EVERYONE = 0xFFFFFFFF
INF = 0xFFFF
HDR_ANNOUNCE, HDR_REQUEST, HDR_SOLICIT, HDR_ANSWER = 0x59, 0x5A, 0x5B, 0x5C
FLAG_RELAY = 0x01
FLAG_STARTING = 0x02
FLAG_ADDRESS = 0x04
LABEL = b"tern v0 announce"
SIG = 64
REF_LEN = 32
NAMED_ROUNDS = 8
LINK_MARGIN, LINK_BAND = 0, 3 * 16  # sixteenths of a dB
ROUTES_KEPT = 4
REPLACE_BAND = 6 * 16
DEFAULT_HOPS = 6
DEFAULT_BUSY = 500000
POWER_K, POWER_MARGIN = 8, 10
METRIC_MAX = 0x7FFE  # a route's metric gives up its top bit to say its destination is a leaf
LEAF_BIT = 0x8000
JITTER = 2
SOLICIT_SPARSE = 4
SOLICIT_TRIES = 3
SOLICIT_HOPS = 3
ANSWER_WINDOW = 16
SOLICIT_LEN, ANSWER_LEN = 12, 13


def rid(address):
    h = hashlib.sha256(b"tern routing id" + address).digest()
    for i in range(0, 32, 4):
        v = int.from_bytes(h[i : i + 4], "big")
        if v not in (0, EVERYONE):
            return v
    raise ValueError("no routing id")


def newer(a, b):
    return 1 <= (a - b) % 65536 <= 0x7FFF


def promise_code(seconds):
    if seconds <= 0x7FFF:
        return seconds
    minutes = -(-seconds // 60)
    return 0x8000 | minutes if minutes <= 32766 else 0xFFFF


def promise_read(code):
    if code == 0xFFFF:
        return None
    return (code & 0x7FFF) * 60 if code & 0x8000 else code


def announce(a, seed):
    """The frame, signed with seed, whose address is the sender's; it carries the address if
    a["carries_address"]."""
    out = struct.pack(
        ">BIHHBHHbBB",
        HDR_ANNOUNCE,
        a["sender"],
        a["number"],
        a["seq"],
        (FLAG_RELAY if a["relay"] else 0)
        | (FLAG_STARTING if a["starting"] else 0)
        | (FLAG_ADDRESS if a["carries_address"] else 0),
        a["promise"],
        a["round"],
        a["power"],
        len(a["neighbours"]),
        len(a["routes"]),
    )
    cards, _ = _crypto()
    if a["carries_address"]:
        out += cards.address(seed)
    for n in a["neighbours"]:
        out += struct.pack(">IB", n["id"], n["margin"])
    for r in a["routes"]:
        out += struct.pack(">IHH", r["destination"], r["seq"], r["metric"])
    out += cards.sign(seed, LABEL + out)
    assert len(out) <= 255
    return out


def announce_read(frame, own, held):
    """Whether a node with routing id own, holding the address held for the sender (None if it
    holds none), takes the announce: the address it then holds, or None if it MUST discard it."""
    if len(frame) < 17 + SIG or len(frame) > 255 or frame[0] != HDR_ANNOUNCE:
        return None
    flags, h, r = frame[9], frame[15], frame[16]
    carries = bool(flags & FLAG_ADDRESS)
    if len(frame) != 17 + 32 * carries + 5 * h + 8 * r + SIG:
        return None
    sender = struct.unpack(">I", frame[1:5])[0]
    if flags & ~(FLAG_RELAY | FLAG_STARTING | FLAG_ADDRESS) or sender in (0, EVERYONE, own):
        return None
    cards, valid_address = _crypto()
    key = held
    if carries:
        key = frame[17:49]
        if not valid_address(key) or rid(key) != sender or (held is not None and held != key):
            return None
    if key is None:
        return None
    try:
        cards.Ed25519PublicKey.from_public_bytes(key).verify(frame[-SIG:], LABEL + frame[:-SIG])
    except (cards.InvalidSignature, ValueError):
        return None
    return key


def request(q):
    out = struct.pack(">BIB", HDR_REQUEST, q["next"], len(q["requests"]))
    for r in q["requests"]:
        out += struct.pack(">IHB", r["destination"], r["seq"], r["hops"])
    assert len(out) <= 255
    return out


def solicit(x):
    return struct.pack(">BIHIb", HDR_SOLICIT, x["sender"], x["id"], x["after"], x["power"])


def answer(x):
    return struct.pack(
        ">BIIHBb", HDR_ANSWER, x["sender"], x["leaf"], x["id"], x["margin"], x["power"]
    )


def short_read(frame, own):
    """A solicit's or an answer's fields, or None if a node with routing id own MUST discard it."""
    if len(frame) == SOLICIT_LEN and frame[0] == HDR_SOLICIT:
        sender, id_, after, power = struct.unpack(">IHIb", frame[1:])
        x = {"sender": sender, "id": id_, "after": after, "power": power}
    elif len(frame) == ANSWER_LEN and frame[0] == HDR_ANSWER:
        sender, leaf, id_, margin, power = struct.unpack(">IIHBb", frame[1:])
        x = {"sender": sender, "leaf": leaf, "id": id_, "margin": margin, "power": power}
    else:
        return None
    return None if x["sender"] in (0, EVERYONE, own) else x


def listed_read(field):
    """A listed route's metric field: None for a retraction, else (leaf, metric)."""
    if field & 0x7FFF == 0x7FFF:
        return None
    return bool(field & LEAF_BIT), field & 0x7FFF


def listed_write(leaf, metric):
    return INF if metric is None else (LEAF_BIT if leaf else 0) | metric


def solicit_view(relays):
    """As a leaf with these relay neighbours: whether it solicits there, its anchor (an index, or
    None), and whether it asks after it on its SOLICIT_GAP."""
    def usable(n):
        return n["up"] and not n["out_of_use"]

    def lately(n):
        return n["promise_s"] is None or n["heard_s"] <= 2 * n["promise_s"]

    sparse = sum(1 for n in relays if n["relay"] and usable(n) and lately(n)) <= SOLICIT_SPARSE
    ok = [(n["margin_sixteenths"], i) for i, n in enumerate(relays) if n["relay"] and usable(n)]
    anchor = max(ok)[1] if ok else None
    if ok:
        assert [m for m, _ in ok].count(max(ok)[0]) == 1, "the vectors leave no tie to break"
    asks = sparse and (anchor is None or not lately(relays[anchor]))
    return sparse, anchor, asks


def answering(own, asked):
    """Whether a relay answers a solicit with its own margin for the leaf `own` (sixteenths of a
    dB), the most it waits, in airtimes of the answer, and whether others' answers cancel it."""
    if own < LINK_MARGIN:
        return False, None, None
    return True, JITTER if asked else ANSWER_WINDOW, not asked


def answered(asked, doubt, unanswered, asked_heard, others_heard, anchor_now, attached_before,
             anchor_heard=None, anchor_heard_first=False):
    """What a leaf does once its solicit's SOLICIT_WAIT is over, and then its doubt, its count of
    solicits wholly unanswered, and whether it heard its anchor in the first of a pair. asked is
    "anchor", "another" or None; anchor_now is "attached", "other" or None; anchor_heard, with
    asked "another", whether the leaf heard from the relay that was its anchor when it asked
    (None for none), and anchor_heard_first whether it did in the first solicit of the pair."""
    if asked is not None and asked_heard:
        return "settled", False, 0, False
    # A solicit another relay answered had an answer: the streak of those with none is broken.
    unanswered = unanswered + 1 if not others_heard else 0
    if asked is not None and not doubt:
        return (("again" if unanswered < SOLICIT_TRIES else "waits"), True, unanswered,
                anchor_heard is True)
    if not others_heard:
        return "waits", False, unanswered, False
    first = asked is None and not attached_before  # takes its anchor without raising its seq
    # Re-attached to, too, when the anchor it had when it asked has gone silent with the rest, in
    # both solicits of the pair: one lost answer moves no leaf.
    silent = asked in ("anchor", None) or (anchor_heard is False and not anchor_heard_first)
    moves = silent and anchor_now not in (None, "attached") and not first
    return ("reattaches" if moves else "moved"), False, 0, False


def out_after(moved, up, out, heard, heard_first=False):
    """Whether a relay neighbour is out of use once a leaf's solicit's answers are in: one heard is
    in use again; one it may use and did not hear, in this solicit or in the first of the pair,
    goes out of use if the leaf has moved."""
    if heard or heard_first:
        return False
    return out or (moved and up)


def given_up(relays, at, hops):
    """A leaf gives `hops` hops up in a row at relays[at]: whether each relay is then out of use,
    whether it asks, after which relay (an index, or None) and whether that was its anchor."""
    sparse, anchor, _ = solicit_view(relays)
    n = relays[at]
    if hops >= SOLICIT_HOPS and sparse and n["relay"] and n["up"] and not n["out_of_use"]:
        outs = [x["out_of_use"] or i == at for i, x in enumerate(relays)]
        return outs, True, at, anchor == at
    return [x["out_of_use"] for x in relays], False, None, False


def heard_elsewhere(up, out, relay, own_seq, offered_seq, retracts):
    """Whether a node takes a neighbour out of use when another neighbour offers a route to it: it
    is a leaf whose link is up, and the route's seq is newer than its own announce gave."""
    if out:
        return True
    return up and not relay and not retracts and newer(offered_seq, own_seq)


def sample(kind, leaf, relay, floor, theirs, up, full, power, snr, margin, sf=9):
    """A node's state for a neighbour it keeps after hearing a solicit or an answer from it: the
    floor, the margin it gave, and whether the link is up. An answer for this node (kind
    "answer to me") from a relay, heard by a leaf, gives the margin."""
    floor = floor_next(floor, power, snr, sf)
    if kind == "answer to me" and leaf and relay:
        theirs = margin
    return floor, theirs, link_next(up, 16 * full - floor, theirs)


def snr_floor_quarters(sf):
    return -30 - 10 * (sf - 7)


def floor_next(floor, power, snr_quarters, sf):
    """The floor, in sixteenths of a dB, after an announce sent at power dBm is heard."""
    sample = 16 * power - 4 * (snr_quarters - snr_floor_quarters(sf))
    return sample if floor is None else (3 * floor + sample) // 4


def margin_byte(full_power, floor):
    return max(1, min(255, (16 * full_power - floor) // 16 + 128))


def link_next(up, mine, theirs):
    """Whether the link is up: mine in sixteenths of a dB, theirs a margin byte or None."""
    if mine is None or theirs is None:
        return False
    m = min(mine, 16 * (theirs - 128))
    return m >= (LINK_MARGIN - LINK_BAND if up else LINK_MARGIN)


def withdrawn(named, number, round_):
    allowed = min(NAMED_ROUNDS * max(round_, 1) + 1, 0x7FFF)
    return (number - named) % 65536 >= allowed


def numbering(last, number, starting, was_starting):
    """What a node does with an announce from a neighbour it knows. Numbers survive a restart, so
    an announce that is not newer is a copy, late or a recording, starting or not, however long
    the neighbour has been silent."""
    if not newer(number, last):
        return "discard"
    return "again" if starting and not was_starting else "take"


def link_cost(sf, bw):
    return max(1, -(-phy.airtime_ns(sf, bw, REF_LEN) // 1_000_000))


def feasible(fd, seq, metric):
    return fd is None or newer(seq, fd["seq"]) or (seq == fd["seq"] and metric < fd["metric"])


def total(metric, cost):
    return min(metric + cost, METRIC_MAX)


def select(fd, cost, routes, selected):
    """The index of the route selected, or None. A route whose neighbour the node may not use (its
    link down, or out of use) is no choice, the selected one included."""
    ok = [(i, total(r["metric"], cost)) for i, r in enumerate(routes)
          if r.get("usable", True) and feasible(fd, r["seq"], r["metric"])]
    cur = next((t for i, t in ok if i == selected), None)
    if cur is not None:
        # Kept unless another is lower by more than a tenth of it, or no higher with a newer seq;
        # then the best of those.
        seq = routes[selected]["seq"]
        ok = [
            (i, t) for i, t in ok
            if i != selected and (10 * t < 9 * cur or (t <= cur and newer(routes[i]["seq"], seq)))
        ]
        if not ok:
            return selected
    best = None
    for i, t in ok:
        # Of the lowest, the newest seq: a leaf that has moved raised it.
        if best is None or t < best[1] or (
            t == best[1] and newer(routes[i]["seq"], routes[best[0]]["seq"])
        ):
            best = (i, t)
    return None if best is None else best[0]


def rank(fd, cost, r):
    """What a route is worth keeping: selectable, then the newer seq, then the lower metric."""
    return (feasible(fd, r["seq"], r["metric"]), r["seq"], total(r["metric"], cost))


def below(a, b):
    if a[0] != b[0]:
        return b[0]
    if a[1] != b[1]:
        return newer(b[1], a[1])
    return a[2] > b[2]


def replaces(fd, cost, routes, selected, offered):
    assert len(routes) == ROUTES_KEPT
    worst = None
    for i, r in enumerate(routes):
        if i == selected:
            continue
        k = rank(fd, cost, r)
        if worst is None or not below(worst[1], k):
            worst = (i, k)
    return worst[0] if below(worst[1], rank(fd, cost, offered)) else None


def place(neighbours, floor):
    """Which neighbour of a full table a node heard with `floor` takes the place of, or None: one
    out of use first, whatever its link and whatever the floor."""
    out = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours) if n["out_of_use"]]
    if out:
        worst, at = max(out)
        assert [f for f, _ in out].count(worst) == 1, "the vectors leave no tie to break"
        return at
    down = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours) if not n["up"]]
    if not down:
        return None
    worst, at = max(down)
    assert [f for f, _ in down].count(worst) == 1, "the vectors leave no tie to break"
    return at if floor + REPLACE_BAND <= worst else None


def leaf_of(relay, listed, selected, was):
    """Whether a node takes a destination to be a leaf: relay is what the destination's own last
    announce said, or None if the node does not keep it as a neighbour; listed is, for each route
    the node holds to it, whether its neighbour listed it as a leaf; selected an index into listed,
    or None; was what it took before."""
    if relay is not None:
        return not relay
    if selected is not None:
        return listed[selected]
    return was


def power_every(leaf, neighbours, lowest, full):
    """What a frame for every neighbour goes at, in dBm: the POWER_K-th lowest floor plus
    POWER_MARGIN, rounded up and kept between lowest and full, with POWER_K floors known; else
    full. A leaf leaves out its neighbours out of use. Floors are in sixteenths of a dBm."""
    floors = sorted(n["floor_sixteenths"] for n in neighbours
                    if not (leaf and n["out_of_use"]))
    if len(floors) < POWER_K:
        return full
    return max(lowest, min(full, -(-(floors[POWER_K - 1] + 16 * POWER_MARGIN) // 16)))


def default_next(leaf, starting, busy_ppm, neighbours, tried):
    """The neighbour a leaf hands a frame with no route to: the nearest relay it may use, or with
    none, the nearest relay it hears that is not out of use; or None."""
    if not leaf or starting or busy_ppm >= DEFAULT_BUSY:
        return None
    ok = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours)
          if n["relay"] and n["up"] and not n["out_of_use"] and i not in tried]
    if not ok:
        ok = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours)
              if n["relay"] and not n["out_of_use"] and i not in tried]
    if not ok:
        return None
    best = min(ok)
    assert [f for f, _ in ok].count(best[0]) == 1, "the vectors leave no tie to break"
    return best[1]


def default_metric(cost):
    return min(DEFAULT_HOPS * cost, METRIC_MAX)


def self_check():
    _crypto()[0].self_check()
    assert newer(1, 0) and newer(0, 0xFFFF) and not newer(0, 0) and not newer(0, 1)
    assert newer(0x7FFF, 0) and not newer(0x8000, 0)
    assert promise_code(32767) == 32767 and promise_code(32768) == 0x8000 | 547
    assert promise_read(promise_code(40000)) == 40020
    assert promise_code(32766 * 60) == 0xFFFE and promise_code(32766 * 60 + 1) == 0xFFFF
    # SF9 demodulates down to -12.5 dB. A frame sent at 2 dBm and heard at +11.5 dB was 24 dB
    # louder than it needed to be: a floor of -22 dBm, and from 22 dBm a margin of 44 dB.
    f = floor_next(None, 2, 46, 9)
    assert f == -22 * 16 and margin_byte(22, f) == 128 + 44
    # Heard exactly at the floor, the sample is the power: (3 * -15 + 0) / 4 = -11.25, down to -12.
    assert floor_next(-15, 0, -50, 9) == -12
    assert numbering(5, 6, False, False) == "take"
    assert numbering(5, 4, False, False) == "discard"
    assert numbering(5, 4, True, False) == "discard"  # a recorded starting announce
    assert numbering(5, 6, True, False) == "again"
    assert numbering(5, 6, True, True) == "take"
    assert not withdrawn(10, 18, 1) and withdrawn(10, 19, 1) and withdrawn(0xFFFF, 8, 0)
    two = [{"floor_sixteenths": 0, "up": False, "out_of_use": False},
           {"floor_sixteenths": 160, "up": True, "out_of_use": False}]
    assert place(two, -96) == 0 and place(two, -95) is None
    two[1]["out_of_use"] = True
    assert place(two, 9999) == 1
    r = [{"floor_sixteenths": -100, "up": True, "relay": True, "out_of_use": False},
         {"floor_sixteenths": -300, "up": True, "relay": False, "out_of_use": False}]
    assert default_next(True, False, 0, r, []) == 0 and default_next(False, False, 0, r, []) is None
    r[0]["out_of_use"] = True
    assert default_next(True, False, 0, r, []) is None
    assert default_metric(70) == 420 and default_metric(20000) == METRIC_MAX
    # As good, newer wins; a tenth better at an older seq still moves.
    two = [{"seq": 5, "metric": 100}, {"seq": 6, "metric": 100}]
    assert select(None, 54, two, None) == 1 and select(None, 54, two, 0) == 1
    assert select(None, 54, [{"seq": 6, "metric": 100}, {"seq": 5, "metric": 10}], 0) == 1
    assert listed_read(0xFFFF) is None and listed_read(0x7FFF) is None
    assert listed_read(0x8036) == (True, 54) and listed_write(True, 54) == 0x8036
    assert answered("anchor", False, 0, False, True, "other", True)[:3] == ("again", True, 0)
    assert answered("anchor", True, 0, False, True, "other", True)[:3] == ("reattaches", False, 0)
    assert answered(None, False, 0, False, True, "other", False)[:3] == ("moved", False, 0)
    assert answering(-1, True) == (False, None, None) and answering(0, False) == (True, 16, True)


def build():
    self_check()
    addresses = [bytes([i]) * 32 for i in (0x00, 0x11, 0xA5)] + [bytes(range(32))]
    a, b, c, d = (rid(x) for x in addresses)

    cards, _ = _crypto()
    seeds = cards.seeds()
    signers = [cards.address(x) for x in seeds]
    sa, sb, sc = (rid(x) for x in signers)
    announces = [
        {
            "sender": sa, "number": 0xFFFF, "seq": 0, "relay": False, "starting": True,
            "carries_address": True, "promise": 600, "round": 0, "power": 22, "neighbours": [],
            "routes": [],
        },
        {
            "sender": sb, "number": 0x0102, "seq": 0x8001, "relay": True, "starting": False,
            "carries_address": False, "promise": promise_code(40000), "round": 2, "power": -9,
            "neighbours": [{"id": a, "margin": 128}, {"id": c, "margin": 255}],
            "routes": [
                {"destination": c, "seq": 7, "metric": 54},
                {"destination": d, "seq": 0xFFFE, "metric": INF},
            ],
        },
        {
            "sender": sc, "number": 5, "seq": 9, "relay": True, "starting": False,
            "carries_address": False, "promise": 0xFFFF, "round": 1, "power": 2,
            "neighbours": [],
            "routes": [{"destination": 0x10000 + i, "seq": i, "metric": 54 * i} for i in range(1, 22)],
        },
        {
            "sender": sb, "number": 0x0103, "seq": 0x8001, "relay": True, "starting": False,
            "carries_address": True, "promise": 600, "round": 1, "power": 14,
            "neighbours": [{"id": a, "margin": 130}],
            "routes": [{"destination": c, "seq": 7, "metric": 54}],
        },
        {
            "sender": sc, "number": 6, "seq": 9, "relay": True, "starting": False,
            "carries_address": False, "promise": 600, "round": 1, "power": 8,
            "neighbours": [],
            "routes": [
                {"destination": a, "seq": 0x0100, "metric": listed_write(True, 54)},
                {"destination": d, "seq": 3, "metric": listed_write(False, 0x7FFE)},
                {"destination": b, "seq": 4, "metric": listed_write(True, None)},
            ],
        },
    ]
    signer = {sa: 0, sb: 1, sc: 2}
    requests = [
        {"next": EVERYONE, "requests": [{"destination": d, "seq": 0, "hops": 0}]},
        {
            "next": b,
            "requests": [
                {"destination": c, "seq": 8, "hops": 32},
                {"destination": d, "seq": 0xFFFF, "hops": 1},
            ],
        },
    ]
    for x in announces:
        k = signer[x["sender"]]
        x["seed"] = seeds[k].hex()
        x["address"] = signers[k].hex()
        x["frame"] = announce(x, seeds[k]).hex()
    for x in requests:
        x["frame"] = request(x).hex()
    solicits = [
        {"sender": a, "id": 0, "after": b, "power": 22},
        {"sender": d, "id": 0xFFFF, "after": EVERYONE, "power": -9},
    ]
    answers = [
        {"sender": b, "leaf": a, "id": 0, "margin": 128, "power": 14},
        {"sender": c, "leaf": d, "id": 0xFFFF, "margin": 1, "power": -9},
    ]
    for x in solicits:
        x["frame"] = solicit(x).hex()
        assert short_read(solicit(x), 0x12345678) == {k: v for k, v in x.items() if k != "frame"}
    for x in answers:
        x["frame"] = answer(x).hex()
        assert short_read(answer(x), 0x12345678) == {k: v for k, v in x.items() if k != "frame"}
    assert len(bytes.fromhex(announces[2]["frame"])) == 249

    good = bytes.fromhex(announces[1]["frame"])  # carries no address
    full = bytes.fromhex(announces[3]["frame"])  # carries it
    ask = request(requests[1])
    mine = announce({**announces[0], "sender": d, "carries_address": False}, seeds[0])
    small = cards.ORDER_8
    stranger = announce({**announces[3], "sender": rid(small)}, seeds[1])
    stranger = stranger[:17] + small + stranger[49:]
    other = announce({**announces[3], "sender": sa}, seeds[1])  # b's address, as a's routing id
    other = other[:17] + signers[1] + other[49:]
    flipped = bytearray(good)
    flipped[-1] ^= 0x01
    tampered = bytearray(good)
    tampered[14] ^= 0x01  # the power it was sent at
    rejected = [
        {"why": "an announce a byte short", "frame": good[:-1].hex()},
        {"why": "an announce a byte long", "frame": (good + b"\x00").hex()},
        {"why": "an announce shorter than its head and signature", "frame": good[:80].hex()},
        {"why": "an announce with an unknown flag", "frame": (good[:9] + b"\x09" + good[10:]).hex()},
        {"why": "an announce from routing id 0", "frame": (good[:1] + bytes(4) + good[5:]).hex()},
        {
            "why": "an announce from routing id ffffffff",
            "frame": (good[:1] + b"\xff" * 4 + good[5:]).hex(),
        },
        {"why": "an announce from the receiver's own routing id", "frame": mine.hex()},
        {"why": "an announce whose signature is not its sender's", "frame": bytes(flipped).hex()},
        {"why": "an announce changed after it was signed", "frame": bytes(tampered).hex()},
        {"why": "an announce carrying an address of small order", "frame": stranger.hex()},
        {"why": "an announce carrying an address not its sender's", "frame": other.hex()},
        {"why": "a request a byte short", "frame": ask[:-1].hex()},
        {"why": "a request a byte long", "frame": (ask + b"\x00").hex()},
        {"why": "a request with nothing in it", "frame": (ask[:5] + b"\x00").hex()},
    ]
    sol = solicit({"sender": a, "id": 1, "after": b, "power": 22})
    ans = answer({"sender": b, "leaf": a, "id": 1, "margin": 140, "power": 22})
    rejected += [
        {"why": "a solicit a byte short", "frame": sol[:-1].hex()},
        {"why": "a solicit a byte long", "frame": (sol + b"\x00").hex()},
        {"why": "a solicit from routing id 0", "frame": (sol[:1] + bytes(4) + sol[5:]).hex()},
        {
            "why": "a solicit from the receiver's own routing id",
            "frame": solicit({"sender": d, "id": 1, "after": b, "power": 22}).hex(),
        },
        {"why": "an answer a byte short", "frame": ans[:-1].hex()},
        {"why": "an answer a byte long", "frame": (ans + b"\x00").hex()},
        {
            "why": "an answer from routing id ffffffff",
            "frame": (ans[:1] + b"\xff" * 4 + ans[5:]).hex(),
        },
    ]
    own = d  # the receiver's routing id, the last of ids
    for x in rejected:
        f = bytes.fromhex(x["frame"])
        if f[0] == HDR_ANNOUNCE:
            sender = struct.unpack(">I", f[1:5])[0] if len(f) >= 5 else 0
            for held in (None, signers[signer[sender]] if sender in signer else None):
                assert announce_read(f, own, held) is None, x["why"]
        elif f[0] in (HDR_SOLICIT, HDR_ANSWER):
            assert short_read(f, own) is None, x["why"]

    # Whether a node takes an announce depends on the address it holds for the sender.
    verified = []
    for which, held, takes in [
        (3, None, True),  # it carries the address
        (3, 1, True),  # and it is the one held
        (1, 1, True),  # it does not, and the node holds it
        (1, None, False),  # it does not, and the node holds none: nothing to check it with
        (1, 2, False),  # it does not, and the signature is not that of the address held
        (0, None, True),
    ]:
        f = bytes.fromhex(announces[which]["frame"])
        key = None if held is None else signers[held]
        got = announce_read(f, own, key)
        assert (got is not None) == takes, (which, held)
        holds = got if got is not None else key  # a discarded frame changes nothing
        verified.append(
            {
                "announce": which,
                "held_address": None if key is None else key.hex(),
                "takes": takes,
                "holds_address": None if holds is None else holds.hex(),
            }
        )

    floors = []
    for sf, full, heard in [
        (9, 22, [(2, 46), (2, 44), (2, -40), (-9, -50), (22, 20)]),
        (7, 14, [(14, -30), (14, -29), (14, -31), (14, -27), (10, 40)]),
        (9, -9, [(22, -50), (22, 127)]),
    ]:
        f, steps = None, []
        for power, snr in heard:
            f = floor_next(f, power, snr, sf)
            steps.append(
                {
                    "power": power,
                    "snr_quarter_db": snr,
                    "floor_sixteenths": f,
                    "margin": margin_byte(full, f),
                }
            )
        floors.append({"spreading_factor": sf, "full_power": full, "heard": steps})

    up, links = False, []
    for mine_, theirs in [
        (None, 140), (160, None), (-1, 140), (160, 127), (0, 128), (-48, 140), (160, 125),
        (-49, 140), (-16, 127), (0, 200), (320, None), (320, 128),
    ]:
        up = link_next(up, mine_, theirs)
        links.append({"own_margin_sixteenths": mine_, "their_margin": theirs, "up": up})

    named = [
        {"named": n, "number": k, "round": r, "withdrawn": withdrawn(n, k, r)}
        for n, k, r in [
            (10, 10, 1), (10, 18, 1), (10, 19, 1), (10, 18, 0), (10, 19, 0), (0xFFFC, 4, 1),
            (0xFFFC, 5, 1), (100, 124, 3), (100, 125, 3), (0, 0x7FFE, 0x7FFF),
            (0, 0x7FFF, 0x7FFF), (0, 0x8000, 0x7FFF),
        ]
    ]

    numbered = [
        {
            "last": last, "number": number, "starting": starting, "was_starting": was,
            "does": numbering(last, number, starting, was),
        }
        for last, number, starting, was in [
            (10, 11, False, False), (10, 10, False, False), (10, 9, False, False),
            (10, 11, True, False), (10, 9, True, False), (10, 10, True, False),
            (10, 11, True, True), (10, 9, True, True), (10, 11, False, True),
            (0xFFFF, 0, False, False), (0, 0x7FFF, False, False), (0, 0x8000, False, False),
            (0, 0x8000, True, False),
        ]
    ]

    costs = [
        {"profile": name, "link_cost": link_cost(sf, bw)}
        for name, _freq, bw, sf, _eirp, _ppm, _window in phy.PROFILES
    ]

    fd = {"seq": 10, "metric": 162}
    feas = [
        {
            "feasibility_distance": f,
            "routes": [{"seq": s, "metric": m, "feasible": feasible(f, s, m)} for s, m in routes],
        }
        for f, routes in [
            (None, [(0, 0), (9, 0x7FFE)]),
            (fd, [(10, 161), (10, 162), (10, 163), (11, 5000), (9, 0), (0x8009, 0), (0x800A, 0)]),
            ({"seq": 0xFFFF, "metric": 54}, [(0, 9999), (0xFFFF, 53), (0xFFFE, 0)]),
        ]
    ]

    def routes_of(pairs):
        return [{"seq": s, "metric": m} for s, m in pairs]

    selection = []
    for f, cost, pairs, sel in [
        (None, 54, [(3, 108), (3, 54), (3, 162)], None),
        (None, 54, [(3, 108), (3, 54), (3, 162)], 0),
        (None, 54, [(3, 546), (3, 486)], 0),
        (None, 54, [(3, 546), (3, 485)], 0),
        (fd, 54, [(10, 162), (10, 54), (9, 0)], None),
        (fd, 54, [(10, 162), (10, 200), (9, 0)], 0),
        (fd, 54, [(10, 162), (11, 500), (10, 108)], 1),
        (fd, 54, [(10, 162), (11, 500), (10, 54)], 1),
        (None, 54, [(1, 0x7FFE), (1, 0x7FF0)], 0),
        # Of routes as good, the newer seq; the selected route gives way to one as good and newer,
        # however little better, but not to one older, nor to one newer and worse.
        (None, 54, [(3, 108), (4, 108)], None),
        (None, 54, [(4, 108), (3, 108)], None),
        (None, 54, [(3, 108), (4, 108)], 0),
        (None, 54, [(3, 108), (4, 100)], 0),
        (None, 54, [(4, 108), (3, 108)], 0),
        (None, 54, [(3, 108), (4, 109)], 0),
        (None, 54, [(3, 108), (2, 0)], 0),
        (fd, 54, [(10, 54), (11, 54), (11, 108)], 0),
        # Selected, an older route a little cheaper, and a newer one no dearer: the newer.
        (None, 54, [(10, 100), (9, 99), (11, 100)], 0),
        # Of those that may take its place, the cheapest, whatever its seq.
        (None, 54, [(10, 1000), (9, 10), (11, 900)], 0),
        (None, 54, [(0xFFFF, 54), (0, 54)], 0),  # newer across the wrap
        (None, 54, [], None),
        # The selected route's neighbour out of use: the route is dropped, for the best usable one
        # whatever hysteresis, or for none.
        (None, 54, [(3, 108, False), (3, 104)], 0),
        (None, 54, [(3, 108, False), (3, 500), (3, 200)], 0),
        (None, 54, [(3, 108, False)], 0),
        (fd, 54, [(10, 54, False), (10, 162)], 0),  # the other infeasible: none
        # nor is a route through one out of use selected in its place
        (None, 54, [(3, 108), (3, 10, False)], 0),
        (None, 54, [(3, 108), (4, 108, False)], 0),
        (None, 54, [(3, 10, False), (3, 108)], None),
    ]:
        rs = [{"seq": x[0], "metric": x[1], "usable": len(x) < 3 or x[2]} for x in pairs]
        selection.append(
            {
                "feasibility_distance": f,
                "link_cost": cost,
                "routes": rs,
                "selected": sel,
                "selects": select(f, cost, rs, sel),
            }
        )

    kept = []
    four = [(10, 108), (10, 54), (9, 0), (10, 300)]
    for f, pairs, sel, off in [
        (fd, four, 1, (10, 161)),
        (fd, four, 1, (10, 400)),
        (fd, four, 1, (9, 54)),
        (fd, four, 1, (8, 0)),
        (fd, four, 3, (11, 5000)),
        (fd, [(10, 54), (10, 55), (10, 56), (10, 57)], 3, (10, 56)),
        (fd, [(10, 54), (10, 55), (10, 56), (10, 57)], 2, (10, 56)),
        (None, [(1, 54), (2, 5000), (3, 9000), (4, 30000)], 0, (5, 32000)),
        (None, [(1, 54), (2, 5000), (3, 9000), (4, 30000)], 3, (1, 0)),
    ]:
        rs = routes_of(pairs)
        o = {"seq": off[0], "metric": off[1]}
        kept.append(
            {
                "feasibility_distance": f,
                "link_cost": 54,
                "routes": rs,
                "selected": sel,
                "offered": o,
                "replaces": replaces(f, 54, rs, sel, o),
            }
        )

    def table(*rows):
        """Each (floor, up), or (floor, up, out of use)."""
        return [{"floor_sixteenths": x[0], "up": x[1], "out_of_use": len(x) > 2 and x[2]}
                for x in rows]

    down = table((-320, False), (-80, False), (-200, False), (-400, False))
    mixed = table((-320, True), (-80, True), (-200, False), (-400, False))
    places = [
        {"neighbours": t, "floor_sixteenths": f, "replaces": place(t, f)}
        for t, f in [
            (down, -176),  # 6 dB nearer than the furthest
            (down, -175),  # a sixteenth short of it
            (down, -600),
            (down, 0),
            (mixed, -296),  # 6 dB nearer than the furthest whose link is not up
            (mixed, -295),
            (mixed, -176),  # nearer than a link that is up, which stays
            (table((-320, True), (-80, True), (-200, True), (-400, True)), -2000),
            (table((100, False)), 4),
            (table((100, False)), 5),
            # Out of use: given up first, though its link is up and the node heard is further
            (table((-320, True, True), (-80, True), (-200, False), (-400, False)), 0),
            (table((-320, True), (-80, True), (-200, True, True), (-400, True)), -2000),
            # of two out of use, the further
            (table((-320, True, True), (-80, False, True), (-200, False), (-400, False)), -600),
        ]
    ]

    def nb(*rows):
        """Each (floor, up, relay), or (floor, up, relay, out of use)."""
        return [{"floor_sixteenths": x[0], "up": x[1], "relay": x[2],
                 "out_of_use": len(x) > 3 and x[3]} for x in rows]

    near = nb((-320, True, True), (-80, True, True), (-480, True, False), (-200, False, True))
    defaults = [
        {
            "neighbours": t, "leaf": leaf, "starting": starting, "busy_ppm": busy, "tried": tried,
            "next": default_next(leaf, starting, busy, t, tried), "link_cost": cost,
            "metric": default_metric(cost),
        }
        for t, leaf, starting, busy, tried, cost in [
            (near, True, False, 0, [], 70),  # the nearest relay: not the nearer leaf, nor a link down
            (near, True, False, 499999, [], 81),
            (near, True, False, 500000, [], 81),  # busy: none
            (near, True, True, 0, [], 70),  # starting: none
            (near, False, False, 0, [], 70),  # a relay takes no default route
            (near, True, False, 0, [0], 70),  # given up at the nearest: the next
            (near, True, False, 0, [0, 1], 70),  # and at both relays whose links are up: the other
            (near, True, False, 0, [0, 1, 3], 70),  # and at every relay: none
            # no link to a relay up: the nearest relay heard, not the nearer leaf
            (nb((-100, False, True), (-300, False, True), (-480, True, False)), True, False, 0, [], 70),
            (nb((-100, True, False)), True, False, 0, [], 70),  # no relay
            (near, True, False, 0, [], 11000),  # a metric past 0x7FFE is 0x7FFE
            # Out of use: the nearest relay whose link is up is passed over for the next
            (nb((-320, True, True, True), (-80, True, True), (-480, True, False),
                (-200, False, True)), True, False, 0, [], 70),
            # both whose links are up are, and the relay heard is taken
            (nb((-320, True, True, True), (-80, True, True, True), (-480, True, False),
                (-200, False, True)), True, False, 0, [], 70),
            # with no link up, the nearest relay heard is passed over for the next
            (nb((-300, False, True, True), (-100, False, True), (-480, True, False)), True, False,
             0, [], 70),
            # nor is one out of use taken among those heard though its link is still up
            (nb((-320, True, True, True), (-200, False, True)), True, False, 0, [], 70),
            # and with every relay out of use, none
            (nb((-320, True, True, True), (-200, False, True, True)), True, False, 0, [], 70),
        ]
    ]

    leaves = [
        {"relay": relay, "listed": listed_, "selected": sel, "was": was,
         "leaf": leaf_of(relay, listed_, sel, was)}
        for relay, listed_, sel, was in [
            (False, [True], 0, False),  # its own announce says it is a leaf
            # it has taken up the relay's role: its own announce outweighs a stale listed bit
            (True, [True, True], 0, True),
            (True, [], None, True),
            (None, [False, True], 0, True),  # not a neighbour: as the selected route lists it
            (None, [False, True], 1, False),
            (None, [True, True], None, False),  # no route selected: as it took it before
            (None, [], None, True),
        ]
    ]

    def flr(*rows):
        """Each (floor in whole dB, out of use)."""
        return [{"floor_sixteenths": 16 * f, "out_of_use": o} for f, o in rows]

    eight = [(-20 + k, False) for k in range(8)]  # floors -20 to -13 dBm
    powers = [
        {"leaf": leaf, "neighbours": n, "lowest": lo, "full": full,
         "power": power_every(leaf, n, lo, full)}
        for leaf, n, lo, full in [
            (True, flr(*eight), -9, 22),  # the eighth lowest, -13, and 10 dB: -3
            (True, flr(*eight[:7]), -9, 22),  # seven known: full power
            # a nearer neighbour out of use, which would lower it: left out by a leaf
            (True, flr((-30, True), *eight), -9, 22),
            (False, flr((-30, True), *eight), -9, 22),  # but not by a relay
            # one of the eight out of use: seven known, full power for a leaf
            (True, flr(*eight[:7], (-13, True)), -9, 22),
            (False, flr(*eight[:7], (-13, True)), -9, 22),
            # a farther one out of use, past the eighth: no matter
            (True, flr(*eight, (0, True)), -9, 22),
            # the nearest out of use, so the eighth a leaf counts is the farther one in use
            (True, flr(*eight[1:], (-20, True), (5, False)), -9, 22),
            # rounded up, and kept between the lowest and full power
            (True, [{"floor_sixteenths": -16 * 13 - 5 + k, "out_of_use": False}
                    for k in range(8)], -9, 22),
            (True, flr(*[(-40, False)] * 8), -9, 22),
            (True, flr(*[(20, False)] * 8), -9, 22),
        ]
    ]

    # Anything heard from a neighbour out of use brings it back into use; a frame discarded is not
    # heard at all.
    again = [
        {"heard": h, "out_of_use": True, "out_of_use_after": not taken}
        for h, taken in [
            ("announce taken", True), ("announce discarded", False), ("frame passed on", True),
            ("solicit", True), ("answer", True),
        ]
    ]

    listed = []
    for field in [0x0036, 0x8036, 0x7FFE, 0xFFFE, 0x0000, 0x8000, 0xFFFF, 0x7FFF]:
        got = listed_read(field)
        listed.append(
            {
                "metric_field": field,
                "retracts": got is None,
                "leaf": None if got is None else got[0],
                "metric": None if got is None else got[1],
                "field": listed_write(*(got if got else (False, None))),
            }
        )

    def relay(up, out, margin, heard, promise, is_relay=True):
        return {"relay": is_relay, "up": up, "out_of_use": out, "margin_sixteenths": margin,
                "heard_s": heard, "promise_s": promise}

    anchors = []
    for rs in [
        [relay(True, False, 80, 100, 600), relay(True, False, 160, 100, 600)],
        [relay(True, False, 80, 100, 600), relay(True, False, 160, 1300, 600)],  # gone quiet
        [relay(True, False, 160, 1200, 600)],  # two promises exactly: not yet
        [relay(True, False, 160, 1201, 600)],
        [relay(True, False, 160, 99999, None)],  # promised nothing: never quiet
        [relay(True, True, 300, 10, 600), relay(False, False, 400, 10, 600),
         relay(True, False, 900, 10, 600, False)],  # out of use, down, and a leaf: no anchor
        [],
        [relay(True, False, 16 * k, 10, 600) for k in range(1, 6)],  # five heard: not sparse
        # five whose links are up, one unheard for long: four heard lately, so sparse
        [relay(True, False, 16 * k, 10, 600) for k in range(1, 5)]
        + [relay(True, False, 80, 2000, 600)],
    ]:
        sparse, anchor, asks = solicit_view(rs)
        anchors.append({"relays": rs, "sparse": sparse, "anchor": anchor, "asks": asks})

    answering_ = []
    for own_, asked in [(0, True), (0, False), (-1, True), (-1, False), (320, False), (-48, True)]:
        ok, wait, cancel = answering(own_, asked)
        answering_.append(
            {"own_margin_sixteenths": own_, "asked": asked, "answers": ok, "wait": wait,
             "cancelled": cancel}
        )

    answered_ = []
    for case in [
        ("anchor", False, 0, True, True, "attached", True),  # it answered: nothing is wrong
        ("anchor", True, 2, True, False, "attached", True),
        ("anchor", False, 0, False, True, "other", True),  # once unanswered: asks again
        ("anchor", False, 0, False, False, None, True),
        ("anchor", False, 2, False, False, None, True),  # a third with no answer: waits
        ("anchor", True, 0, False, True, "other", True),  # twice, and another answered: moves
        ("anchor", True, 0, False, True, "other", False),
        ("anchor", True, 0, False, True, "attached", True),  # to where it last moved: no new seq
        ("anchor", True, 0, False, True, None, True),
        ("anchor", True, 1, False, False, "other", True),  # twice, and none answered: waits
        ("another", True, 0, False, True, "other", True, True),  # not its anchor: no new seq
        (None, False, 0, False, True, "other", True),  # no anchor, then one answered
        (None, False, 0, False, True, "other", False),  # its first: no new seq
        (None, False, 1, False, False, None, False),
        # Another relay answered: the streak of solicits with no answer at all is broken.
        ("anchor", False, 2, False, True, "other", True),
        (None, False, 2, False, True, "other", True),
        # Asked after another relay for hops given up there, and the anchor it had then silent
        # too: it has moved from its anchor, and re-attaches.
        ("another", True, 0, False, True, "other", True, False),
        ("another", True, 0, False, True, "other", True, True),  # its anchor answered: no
        # The first of the pair: whether it heard its anchor is kept for the second.
        ("another", False, 0, False, True, "other", True, True),
        ("another", False, 0, False, True, "other", True, False),
        # Its anchor answered the first of the pair, and its answer to the second was lost: no
        ("another", True, 0, False, True, "other", True, False, True),
        # The relay asked after, out of use for the hops given up there, answers: in use again.
        ("another", False, 0, True, False, "attached", True, True),
    ]:
        case = case + (None,) * (8 - len(case)) + (False,) * (9 - max(len(case), 8))
        does, doubt_after, unanswered_after, first_after = answered(*case)
        (asked, doubt, unanswered, asked_heard, others_heard, anchor_now, before, anchor_heard,
         anchor_first) = case
        moved = does in ("moved", "reattaches")
        # The relay neighbours it has: the one asked after, first, if any - out of use already if
        # it was asked after for hops given up there - one other heard if any was, one it may use
        # and did not hear, one it did not hear and had taken out of use, and one whose link is
        # down.
        assert asked != "another" or anchor_heard is not None, "another relay: say of the anchor"
        assert asked == "another" or anchor_heard is None, "the anchor is asked after, or none"
        second = asked is not None and doubt  # this solicit is the second of a pair
        relays = []
        if asked is not None:  # silent in the first of a pair, or it would have settled
            relays.append({"up": True, "out_of_use": asked == "another", "heard": asked_heard,
                           "heard_first": False})
        if anchor_heard is not None:
            relays.append({"up": True, "out_of_use": False, "heard": anchor_heard,
                           "heard_first": bool(anchor_first)})
        if others_heard:
            relays.append({"up": True, "out_of_use": False, "heard": True, "heard_first": False})
            # one out of use, given up on earlier, that answered: in use again
            relays.append({"up": True, "out_of_use": True, "heard": True, "heard_first": False})
        if second:
            # one that answered the first of the pair, and whose answer to the second was lost
            relays.append({"up": True, "out_of_use": False, "heard": False, "heard_first": True})
        relays += [
            {"up": True, "out_of_use": False, "heard": False, "heard_first": False},
            {"up": True, "out_of_use": True, "heard": False, "heard_first": False},
            {"up": False, "out_of_use": False, "heard": False, "heard_first": False},
        ]
        for x in relays:
            x["out_of_use_after"] = out_after(moved, x["up"], x["out_of_use"], x["heard"],
                                              x["heard_first"])
        answered_.append(
            {"asked": asked, "doubt": doubt, "unanswered": unanswered, "asked_heard": asked_heard,
             "others_heard": others_heard, "anchor_now": anchor_now, "attached_before": before,
             "anchor_heard": anchor_heard, "anchor_heard_first": anchor_first, "relays": relays,
             "does": does, "doubt_after": doubt_after,
             "anchor_heard_first_after": first_after,
             "unanswered_after": unanswered_after}
        )

    given = []
    for rs, at, hops in [
        ([relay(True, False, 80, 10, 600), relay(True, False, 160, 10, 600)], 1, 3),  # its anchor
        ([relay(True, False, 80, 10, 600), relay(True, False, 160, 10, 600)], 0, 3),  # another
        ([relay(True, False, 80, 10, 600), relay(True, False, 160, 10, 600)], 1, 2),  # two: no
        # five relays heard lately: not where it solicits, and nothing goes out of use
        ([relay(True, False, 16 * k, 10, 600) for k in range(1, 6)], 4, 3),
        ([relay(True, True, 80, 10, 600), relay(True, False, 160, 10, 600)], 0, 3),  # out already
        ([relay(False, False, 80, 10, 600), relay(True, False, 160, 10, 600)], 0, 3),  # link down
        # a neighbour that is not a relay
        ([relay(True, False, 80, 10, 600, False), relay(True, False, 160, 10, 600)], 0, 3),
    ]:
        outs, asks, after, anchored = given_up(rs, at, hops)
        given.append({"relays": rs, "at": at, "hops": hops, "out_of_use_after": outs,
                      "asks": asks, "after": after, "anchored": anchored})

    elsewhere = [
        {"up": up, "out_of_use": out, "relay": rl, "own_seq": own, "offered_seq": off,
         "retracts": ret, "out_of_use_after": heard_elsewhere(up, out, rl, own, off, ret)}
        for up, out, rl, own, off, ret in [
            (True, False, False, 5, 6, False),  # a newer seq from elsewhere: it has moved
            (True, False, False, 5, 5, False),  # the same: it has not
            (True, False, False, 5, 4, False),
            (True, False, False, 0xFFFF, 0, False),  # newer across the wrap
            (True, False, False, 5, 6, True),  # a retraction says nothing of it
            (True, False, True, 5, 6, False),  # a relay is not taken out of use so
            (False, False, False, 5, 6, False),  # nor is a leaf whose link is down
            (True, True, False, 5, 4, False),  # out of use already, it stays so
        ]
    ]

    samples = []
    for row in [
        # a leaf hears its relay's answer: the margin given, and the link up at once
        ("answer to me", True, True, 16 * -20, 0, False, 14, 0, 140),
        ("answer to me", True, True, 16 * -20, 0, False, 14, 0, 127),  # less than none: not up
        ("answer to me", False, True, 16 * -20, 0, False, 14, 0, 140),  # a relay takes no margin
        ("answer to me", True, False, 16 * -20, 0, False, 14, 0, 140),  # nor from a leaf
        ("answer to another", True, True, 16 * -20, 130, True, 14, -40, 200),  # a sample only
        ("solicit", False, False, 16 * -20, 135, True, 22, -50, None),  # a relay hears a leaf
        ("solicit", False, False, 16 * 30, 135, True, 22, -50, None),  # and the link goes down
        # From a neighbour out of use, anything heard brings it back into use: the relay a leaf
        # gave hops up at answers it, or a leaf a relay took out of use solicits.
        ("answer to me", True, True, 16 * -20, 140, True, 14, 0, 140, True),
        ("answer to another", True, True, 16 * -20, 130, True, 14, -40, 200, True),
        ("solicit", False, False, 16 * -20, 135, True, 22, -50, None, True),
    ]:
        kind, leaf, rl, floor, theirs, up, power, snr, margin = row[:9]
        out = len(row) > 9 and row[9]
        f, t, u = sample(kind, leaf, rl, floor, theirs, up, 22, power, snr, margin)
        # A relay that hears a solicit answers with the margin it gives the leaf, at the power of
        # a frame for it, if its own margin allows.
        replies = kind == "solicit" and not leaf and answering(16 * 22 - f, False)[0]
        samples.append(
            {"kind": kind, "leaf": leaf, "relay": rl, "kept": True, "floor_sixteenths": floor,
             "their_margin": theirs, "up": up, "out_of_use": out, "full_power": 22,
             "power": power, "snr_quarter_db": snr, "margin": margin, "floor_after": f,
             "their_margin_after": t, "up_after": u, "out_of_use_after": False,
             "answer_margin": margin_byte(22, f) if replies else None,
             "answer_power": max(-9, min(22, -(-(f + 16 * POWER_MARGIN) // 16)))
             if replies else None}
        )
    # From a node it does not keep, a solicit or an answer gives nothing: no neighbour, no answer.
    for kind, leaf in [("solicit", False), ("answer to me", True)]:
        samples.append(
            {"kind": kind, "leaf": leaf, "relay": not leaf, "kept": False,
             "floor_sixteenths": None, "their_margin": None, "up": None, "out_of_use": None,
             "out_of_use_after": None, "full_power": 22,
             "power": 14, "snr_quarter_db": 0, "margin": 140 if kind != "solicit" else None,
             "floor_after": None, "their_margin_after": None, "up_after": None,
             "answer_margin": None, "answer_power": None}
        )

    return {
        "description": "Routing, draft 0 (draft/routing.md). Routing ids, sequence numbers, "
        "promise codes and metrics are numbers; addresses and frames are hex. In floors, powers "
        "are dBm, snr_quarter_db is the signal-to-noise ratio in quarters of a decibel, as the "
        "SX126x reports it, and floor_sixteenths is the floor in sixteenths of a dBm. In links, "
        "own_margin_sixteenths is the node's full power less its floor for the neighbour, in "
        "sixteenths of a decibel, and their_margin is the margin byte the neighbour gave; either "
        "is null when it is missing, and the steps follow one another. In places, neighbours is a "
        "full table, each with the node's floor for it, whether its link is up and whether it is "
        "out of use, "
        "floor_sixteenths is the floor an announce from a node not in it gives, and replaces is "
        "an index into neighbours. In selection and kept, "
        "each route's metric is the one its neighbour announced, every link costs link_cost, and "
        "selected, selects and replaces are indexes into routes. In defaults, each neighbour's "
        "out_of_use says whether it is out of use, tried and next are indexes into neighbours, "
        "busy_ppm is the leaf's busy share in millionths, and metric is the default route's. "
        "Each announce is signed with seed, whose address is address, and carries the address "
        "in the frame if carries_address is true. A rejected frame MUST be "
        "discarded whether or not the receiver holds its sender's address. In verified, announce "
        "is an index into announces, held_address is the address the receiver holds for its "
        "sender (null for none), takes whether it takes the announce rather than discarding it, "
        "and holds_address the address it then holds for the sender, if the rest of the "
        "section then takes the announce from a neighbour. In listed, metric_field is a listed "
        "route's metric as it goes on the air, retracts whether it retracts the route, leaf and "
        "metric what it says otherwise (null for a retraction), and field what a node writes for "
        "them. In anchors, each of relays is a neighbour of a leaf, relay saying whether it is "
        "one, with whether its link is up, whether it is out of use, its link's margin in "
        "sixteenths of a decibel, the seconds since it was heard and its promise in seconds "
        "(null for none); sparse is whether the leaf solicits there, anchor an index into relays "
        "(null for none), and asks whether it asks after it on its SOLICIT_GAP. In answering, "
        "own_margin_sixteenths is the relay's full power less its floor for the leaf, asked "
        "whether the solicit asks after it, wait the most its answer waits in airtimes of the "
        "answer (null if it does not answer), and cancelled whether others' answers cancel it. "
        "In answered, asked is the relay the leaf asked after, its anchor when it asked, another "
        "or null for none; asked_heard and others_heard whether it heard from that relay and "
        "from any other in SOLICIT_WAIT; anchor_now whether its anchor now is the one it last "
        "re-attached to, another, or null for none; attached_before whether it has re-attached "
        "before; does is settled, again, waits, moved or reattaches. In leaves, relay is what the "
        "destination's own last announce said of its role (null if the node does not keep it as "
        "a neighbour), listed whether each route the node holds to it was listed as one to a "
        "leaf, selected an index into listed (null for none), was what the node took before, and "
        "leaf what it takes now. In selection, a route whose usable is false goes through a "
        "neighbour the node may not use: its link is down or it is out of use. In powers, a "
        "node, a leaf or not, with the neighbours given, each with its floor and whether it is "
        "out of use, and with the lowest and full power given in dBm, sends a frame for every "
        "neighbour at power. In answered, relays are the leaf's relay neighbours, the one asked "
        "after first if any, each with whether its link is up, whether it was out of use, "
        "whether the leaf heard from it in SOLICIT_WAIT, and whether it is out of use after. In "
        "given_up, relays are a leaf's neighbours as in anchors, at the index of the one hops "
        "hops in a row are given up at, out_of_use_after whether each is then out of use, asks "
        "whether the leaf then asks, after the index it asks after (null for none) and anchored "
        "whether that was its anchor. In elsewhere, a node keeps a neighbour whose link is up or "
        "not, out of use or not and a relay or not, whose own last announce gave own_seq, and "
        "another neighbour offers a route to it at offered_seq, a retraction or not; "
        "out_of_use_after is whether the first is then out of use. In samples, a node, a leaf or "
        "not, keeps a neighbour, a relay or not, with floor_sixteenths, their_margin (0 for none) "
        "and its link up or not, and hears from it a solicit or an answer (an answer to me is "
        "one for this node) sent at power, heard at snr_quarter_db at SF9, with margin; its full "
        "power is full_power, and the floor, the margin and the link are then the ones after; "
        "a relay that answers a solicit answers with answer_margin at answer_power, both null "
        "where it does not answer. Where kept is false the node does not keep the sender, and "
        "takes nothing from the frame: it keeps no neighbour for it and answers nothing. "
        "out_of_use and out_of_use_after say whether the neighbour is out of use before and "
        "after: heard from, it is in use again. In answered, anchor_heard, where the leaf asked "
        "after a relay that was not its anchor, says whether it heard from the relay that was "
        "(null where there was none, or the anchor is the one asked after), and that relay is "
        "among relays; anchor_heard_first whether it heard that anchor in the first solicit of "
        "the pair, which the leaf keeps for the second as anchor_heard_first_after; each relay's "
        "heard_first says whether the leaf heard from it in the first solicit of the pair. In "
        "in_use_again, a node keeps a neighbour out of use and hears from it what heard says: an "
        "announce it takes, one it discards (as a copy, by its number), a frame the neighbour "
        "passed on, a solicit or an answer; out_of_use_after is whether it is then out of use.",
        "generator": "vectors/tools/routing.py",
        "ids": [{"address": x.hex(), "id": rid(x)} for x in addresses],
        "newer": [
            {"a": x, "b": y, "newer": newer(x, y)}
            for x, y in [
                (1, 0), (0, 1), (0, 0), (0, 0xFFFF), (0xFFFF, 0), (0x7FFF, 0), (0x8000, 0),
                (0x8000, 1), (5, 0x8006), (5, 0x8005),
            ]
        ],
        "promises": [
            {"seconds": s, "code": promise_code(s), "read_seconds": promise_read(promise_code(s))}
            for s in [1, 600, 32767, 32768, 32820, 32821, 40000, 1965960, 1965961, 4000000]
        ],
        "announces": announces,
        "requests": requests,
        "solicits": solicits,
        "answers": answers,
        "rejected": rejected,
        "verified": verified,
        "floors": floors,
        "links": links,
        "named": named,
        "places": places,
        "numbering": numbered,
        "costs": costs,
        "feasible": feas,
        "selection": selection,
        "kept": kept,
        "defaults": defaults,
        "listed": listed,
        "anchors": anchors,
        "answering": answering_,
        "answered": answered_,
        "leaves": leaves,
        "powers": powers,
        "given_up": given,
        "elsewhere": elsewhere,
        "samples": samples,
        "in_use_again": again,
    }


def main():
    text = json.dumps(build(), indent=2) + "\n"
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "generate":
        OUT.write_text(text, encoding="utf-8")
    elif mode == "check":
        if OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT} does not match its generator; run 'generate'")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
