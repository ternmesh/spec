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
import cards  # noqa: E402
import phy  # noqa: E402
from first_contact import valid_address  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "routing.json"

EVERYONE = 0xFFFFFFFF
INF = 0xFFFF
HDR_ANNOUNCE, HDR_REQUEST = 0x59, 0x5A
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


def numbering(last, number, promise_passed, starting, was_starting):
    """What a node does with an announce from a neighbour it knows. Numbers survive a restart, so
    a starting announce is late or a recording unless it is newer, as any other is."""
    if not newer(number, last):
        return "again" if promise_passed else "discard"
    return "again" if starting and not was_starting else "take"


def link_cost(sf, bw):
    return max(1, -(-phy.airtime_ns(sf, bw, REF_LEN) // 1_000_000))


def feasible(fd, seq, metric):
    return fd is None or newer(seq, fd["seq"]) or (seq == fd["seq"] and metric < fd["metric"])


def total(metric, cost):
    return min(metric + cost, INF - 1)


def select(fd, cost, routes, selected):
    """The index of the route selected, or None."""
    best = cur = None
    for i, r in enumerate(routes):
        if not feasible(fd, r["seq"], r["metric"]):
            continue
        t = total(r["metric"], cost)
        if i == selected:
            cur = t
        if best is None or t < best[1]:
            best = (i, t)
    if best is None:
        return None
    # Kept unless another is lower by more than a tenth of it.
    if cur is not None and best[0] != selected and not 10 * best[1] < 9 * cur:
        return selected
    return best[0]


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
    """Which neighbour of a full table a node heard with `floor` takes the place of, or None."""
    down = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours) if not n["up"]]
    if not down:
        return None
    worst, at = max(down)
    assert [f for f, _ in down].count(worst) == 1, "the vectors leave no tie to break"
    return at if floor + REPLACE_BAND <= worst else None


def default_next(leaf, starting, busy_ppm, neighbours, tried):
    """The neighbour a leaf hands a frame with no route to: the nearest relay it may use, or None."""
    if not leaf or starting or busy_ppm >= DEFAULT_BUSY:
        return None
    ok = [(n["floor_sixteenths"], i) for i, n in enumerate(neighbours)
          if n["relay"] and n["up"] and i not in tried]
    if not ok:
        return None
    best = min(ok)
    assert [f for f, _ in ok].count(best[0]) == 1, "the vectors leave no tie to break"
    return best[1]


def default_metric(cost):
    return min(DEFAULT_HOPS * cost, INF - 1)


def self_check():
    cards.self_check()
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
    assert numbering(5, 6, False, False, False) == "take"
    assert numbering(5, 4, False, False, False) == "discard"
    assert numbering(5, 4, True, False, False) == "again"
    assert numbering(5, 4, False, True, False) == "discard"  # a recorded starting announce
    assert numbering(5, 6, False, True, False) == "again"
    assert numbering(5, 6, False, True, True) == "take"
    assert not withdrawn(10, 18, 1) and withdrawn(10, 19, 1) and withdrawn(0xFFFF, 8, 0)
    two = [{"floor_sixteenths": 0, "up": False}, {"floor_sixteenths": 160, "up": True}]
    assert place(two, -96) == 0 and place(two, -95) is None
    r = [{"floor_sixteenths": -100, "up": True, "relay": True},
         {"floor_sixteenths": -300, "up": True, "relay": False}]
    assert default_next(True, False, 0, r, []) == 0 and default_next(False, False, 0, r, []) is None
    assert default_metric(70) == 420 and default_metric(20000) == INF - 1


def build():
    self_check()
    addresses = [bytes([i]) * 32 for i in (0x00, 0x11, 0xA5)] + [bytes(range(32))]
    a, b, c, d = (rid(x) for x in addresses)

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
    own = d  # the receiver's routing id, the last of ids
    for x in rejected:
        f = bytes.fromhex(x["frame"])
        if f[0] == HDR_ANNOUNCE:
            sender = struct.unpack(">I", f[1:5])[0] if len(f) >= 5 else 0
            for held in (None, signers[signer[sender]] if sender in signer else None):
                assert announce_read(f, own, held) is None, x["why"]

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
            "last": last, "number": number, "promise_passed": passed, "starting": starting,
            "was_starting": was, "does": numbering(last, number, passed, starting, was),
        }
        for last, number, passed, starting, was in [
            (10, 11, False, False, False), (10, 10, False, False, False),
            (10, 10, True, False, False), (10, 9, False, False, False),
            (10, 9, True, False, False), (10, 11, False, True, False),
            (10, 9, False, True, False), (10, 10, False, True, False),
            (10, 11, False, True, True), (10, 9, False, True, True),
            (10, 11, False, False, True), (0xFFFF, 0, False, False, False),
            (0, 0x7FFF, False, False, False), (0, 0x8000, False, False, False),
            (0, 0x8000, True, False, False),
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
            (None, [(0, 0), (9, 0xFFFE)]),
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
        (None, 54, [(1, 0xFFFE), (1, 0xFFF0)], 0),
        (None, 54, [], None),
    ]:
        rs = routes_of(pairs)
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
        (None, [(1, 54), (2, 5000), (3, 9000), (4, 60000)], 0, (5, 65000)),
        (None, [(1, 54), (2, 5000), (3, 9000), (4, 60000)], 3, (1, 0)),
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

    def table(*pairs):
        return [{"floor_sixteenths": f, "up": u} for f, u in pairs]

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
        ]
    ]

    def nb(*triples):
        return [{"floor_sixteenths": f, "up": u, "relay": r} for f, u, r in triples]

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
            (near, True, False, 0, [0, 1], 70),  # and at both relays whose links are up: none
            (nb((-100, True, False)), True, False, 0, [], 70),  # no relay
            (near, True, False, 0, [], 11000),  # a metric past 0xFFFE is 0xFFFE
        ]
    ]

    return {
        "description": "Routing, draft 0 (draft/routing.md). Routing ids, sequence numbers, "
        "promise codes and metrics are numbers; addresses and frames are hex. In floors, powers "
        "are dBm, snr_quarter_db is the signal-to-noise ratio in quarters of a decibel, as the "
        "SX126x reports it, and floor_sixteenths is the floor in sixteenths of a dBm. In links, "
        "own_margin_sixteenths is the node's full power less its floor for the neighbour, in "
        "sixteenths of a decibel, and their_margin is the margin byte the neighbour gave; either "
        "is null when it is missing, and the steps follow one another. In places, neighbours is a "
        "full table, each with the node's floor for it and whether its link is up, "
        "floor_sixteenths is the floor an announce from a node not in it gives, and replaces is "
        "an index into neighbours. In selection and kept, "
        "each route's metric is the one its neighbour announced, every link costs link_cost, and "
        "selected, selects and replaces are indexes into routes. In defaults, tried and next are "
        "indexes into neighbours, busy_ppm is the leaf's busy share in millionths, and metric is "
        "the default route's. Each announce is signed with seed, whose address is address, and "
        "carries the address in the frame if carries_address is true. A rejected frame MUST be "
        "discarded whether or not the receiver holds its sender's address. In verified, announce "
        "is an index into announces, held_address is the address the receiver holds for its "
        "sender (null for none), takes whether it takes the announce rather than discarding it, "
        "and holds_address the address it then holds for the sender.",
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
