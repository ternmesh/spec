#!/usr/bin/env python3
"""Generates and checks the test vectors for frames that follow routes (draft/forwarding.md).

    python3 vectors/tools/forwarding.py generate   # rewrite vectors/forwarding.json
    python3 vectors/tools/forwarding.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Floors come from routing.py and airtimes from phy.py,
beside this file.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phy  # noqa: E402
import routing  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "forwarding.json"

HDR_MESSAGE, HDR_ACK = 0x48, 0x50
# A message for the node itself is a message here: the node flag (draft/unicast-security.md).
MESSAGES = (HDR_MESSAGE, HDR_MESSAGE | 0x01)
# First contact's four frames (draft/first-contact.md), and how long each is: the head, a tag,
# for the first the routing id it came from, and the handshake's message.
CONTACT_LEN = {0x51: 56, 0x52: 60, 0x53: 80, 0x54: 24}
RESERVED = (0, 0xFFFFFFFF)
HEAD, TAG = 11, 4
ACK_LEN = HEAD + TAG + 4
MESSAGE_MIN = HEAD + TAG + 8
AT_DEST = 7
HOP_MAX = 32
POWER_MARGIN = 10
STEP = 3
RETRY_JITTER = 4
HEAD_WAIT = 13
# Traces (draft/forwarding.md, Traces): a trace carries the routing id it came from, a trace answer
# its flags and how many entries went out; each entry is a routing id and an SNR in quarter dB.
HDR_TRACE, HDR_ANSWER = 0x56, 0x57
TRACES = (HDR_TRACE, HDR_ANSWER)
TRACE_MIN, ANSWER_MIN, ENTRY = HEAD + TAG + 4, HEAD + TAG + 2, 5
TRACE_ENTRIES = 16
FLAGS = (0, 1, 2)


def head(h):
    return struct.pack(">BBbII", h["hdr"], h["hops"], h["power"], h["next"], h["destination"])


def accepted(frame):
    """Whether a receiver takes a frame at all."""
    if len(frame) > 255 or not frame or frame[0] not in (*MESSAGES, HDR_ACK, *CONTACT_LEN, *TRACES):
        return False
    if frame[0] in CONTACT_LEN and len(frame) != CONTACT_LEN[frame[0]]:
        return False
    if frame[0] == HDR_ACK and len(frame) != ACK_LEN:
        return False
    if frame[0] in MESSAGES and len(frame) < MESSAGE_MIN:
        return False
    if frame[0] in TRACES and entries_of(frame) is None:
        return False
    _, _, _, nxt, dst = struct.unpack(">BBbII", frame[:HEAD])
    return nxt not in RESERVED and dst not in RESERVED


def entries_of(frame):
    """A trace's or a trace answer's entries as (routing id, SNR in quarter dB), and for an answer
    its flags and out; None if the frame is not one a receiver takes."""
    least = TRACE_MIN if frame[0] == HDR_TRACE else ANSWER_MIN
    if len(frame) < least or (len(frame) - least) % ENTRY:
        return None
    entries = [struct.unpack(">Ib", frame[i : i + ENTRY]) for i in range(least, len(frame), ENTRY)]
    if frame[0] == HDR_TRACE:
        return (entries, None, None) if len(entries) <= TRACE_ENTRIES else None
    flags, out = frame[HEAD + TAG], frame[HEAD + TAG + 1]
    if flags not in FLAGS or out > len(entries) or out > TRACE_ENTRIES:
        return None
    if len(entries) - out > TRACE_ENTRIES:
        return None
    return entries, flags, out


def passed_on(sent, heard):
    """Whether heard is sent as its neighbour passes it on: hops one less, and for a trace or a
    trace answer, one entry added at the end."""
    if sent[0] != heard[0] or heard[1] + 1 != sent[1]:
        return False
    if sent[0] in TRACES:
        return len(heard) == len(sent) + ENTRY and heard[AT_DEST : len(sent)] == sent[AT_DEST:]
    return sent[AT_DEST:] == heard[AT_DEST:]


def ends(sent, heard):
    """Whether hearing one frame ends the hop of another this node sent: both whole frames."""
    same_tag = heard[HEAD : HEAD + TAG] == sent[HEAD : HEAD + TAG]
    answered = (sent[0] in MESSAGES and heard[0] == HDR_ACK and same_tag) or (
        sent[0] == HDR_TRACE and heard[0] == HDR_ANSWER and same_tag
    )
    return passed_on(sent, heard) or answered


def teaches(sent, heard):
    """Whether hearing it is a sample of the neighbour's floor: only the frame passed on. An
    acknowledgement or a trace answer ends a hop and teaches nothing, since no node on the way can
    check it."""
    return passed_on(sent, heard)


def hop_heard(frame):
    """Whether a node that has sent a frame listens for the hop to succeed. On the last hop of an
    acknowledgement, a first-contact frame or a trace answer there is nothing to hear."""
    _, _, _, nxt, dst = struct.unpack(">BBbII", frame[:HEAD])
    return frame[0] in MESSAGES or frame[0] == HDR_TRACE or nxt != dst


def entry(rid, snr_quarters):
    return struct.pack(">Ib", rid, max(-128, min(127, snr_quarters)))


def pass_on(frame, rid, snr_quarters):
    """What a relay passes on of a trace or trace answer it received: (hops, the bytes from
    destination on), or None where it drops it."""
    entries, _, out = entries_of(frame)
    full = len(entries) >= TRACE_ENTRIES if out is None else len(entries) - out >= TRACE_ENTRIES
    if frame[1] <= 1 or full:
        return None
    return frame[1] - 1, frame[AT_DEST:] + entry(rid, snr_quarters)


def answer(frame, rid, snr_quarters, flags):
    """The trace answer a node sends to a trace it received: the bytes from destination on, or None
    where it cannot add its entry and drops the trace."""
    entries, _, _ = entries_of(frame)
    if len(entries) >= TRACE_ENTRIES:
        return None
    (source,) = struct.unpack(">I", frame[HEAD + TAG : TRACE_MIN])
    tag = frame[HEAD : HEAD + TAG]
    return (struct.pack(">I", source) + tag + bytes([flags, len(entries) + 1])
            + frame[TRACE_MIN:] + entry(rid, snr_quarters))


def clamp(sixteenths, lowest, full):
    return max(lowest, min(full, -(-sixteenths // 16)))


def needs(power, snr_quarters, sf, lowest, full):
    """What a frame must go at for the node a frame came from to hear it."""
    return clamp(routing.floor_next(None, power, snr_quarters, sf) + 16 * POWER_MARGIN, lowest, full)


def power(neighbour, back, tries, full):
    """What a frame goes at: for its neighbour and the node before, and louder each try."""
    return min(full, max(neighbour, back if back is not None else neighbour) + STEP * tries)


def longest_wait(sf, bw_hz, length):
    """The longest a frame sent again waits first, in nanoseconds: RETRY_JITTER of its airtimes."""
    return RETRY_JITTER * phy.airtime_ns(sf, bw_hz, length)


def symbol_ns(sf, bw_hz):
    return (1 << sf) * 1_000_000_000 // bw_hz


def head_wait(sf, bw_hz):
    """How long a preamble with no header after it holds a node, in nanoseconds."""
    return (phy.PREAMBLE + HEAD_WAIT) * symbol_ns(sf, bw_hz)


def receiving(sf, bw_hz, events, at):
    """Whether a radio that reported events, as (time, what) in order, is receiving at a time."""
    found, header = None, False

    def held(header):
        return phy.airtime_ns(sf, bw_hz, 255) if header else head_wait(sf, bw_hz)

    for when, what in events:
        if when > at:
            break
        if found is not None and when - found >= held(header):
            found = None  # what it was on ran out before this
        if what == "preamble":
            found, header = when, False
        elif what == "header":
            found, header = (when if found is None else found), True
        else:  # the frame ended, or the node began to send
            found = None
    return found is not None and at - found < held(header)


def listen_cases(sf, bw_hz):
    """Each way a reception can go, asked just inside and just outside each bound."""
    sym, wait, longest = symbol_ns(sf, bw_hz), head_wait(sf, bw_hz), phy.airtime_ns(sf, bw_hz, 255)
    start, frame = 1_000_000, phy.airtime_ns(sf, bw_hz, 40)
    found = start + 5 * sym
    lines = [
        ([], [0, start]),
        ([(found, "preamble")], [found - 1, found, found + wait - 1, found + wait]),
        ([(found, "preamble"), (found + 16 * sym, "header")],
         [found + wait, found + longest - 1, found + longest]),
        ([(found, "preamble"), (found + 16 * sym, "header"), (start + frame, "end")],
         [found + 16 * sym, start + frame - 1, start + frame]),
        ([(found, "preamble"), (found + 18 * sym, "end")], [found + 18 * sym - 1, found + 18 * sym]),
        ([(found, "preamble"), (found + 3 * sym, "sent")], [found + 3 * sym - 1, found + 3 * sym]),
        ([(found, "preamble"), (found + 9 * sym, "preamble")],
         [found + wait, found + 9 * sym + wait - 1, found + 9 * sym + wait]),
        ([(found, "header")], [found - 1, found, found + longest - 1, found + longest]),
        # A header that comes after the wait for one ran out is a frame of its own.
        ([(found, "preamble"), (found + wait + 10 * sym, "header")],
         [found + wait, found + wait + 10 * sym, found + longest,
          found + wait + 10 * sym + longest - 1, found + wait + 10 * sym + longest]),
        ([(found, "preamble"), (found + wait, "header")], [found + longest, found + wait + longest - 1]),
        ([(found, "preamble"), (found + wait - 1, "header")], [found + longest - 1, found + longest]),
        ([(found, "preamble"), (found + 16 * sym, "header"), (start + frame, "end"),
          (start + frame + 20 * sym, "preamble")],
         [start + frame + 20 * sym - 1, start + frame + 20 * sym, start + frame + 20 * sym + wait]),
    ]
    return [
        {
            "spreading_factor": sf, "bandwidth_hz": bw_hz,
            "events": [{"at_ns": when, "radio": what} for when, what in events],
            "asks": [{"at_ns": at, "receiving": receiving(sf, bw_hz, events, at)} for at in asks],
        }
        for events, asks in lines
    ]


def self_check():
    # A 35-byte frame at SF9 and 500 kHz is on the air for 69.888 ms by phy.py, which checks its
    # own arithmetic against values worked by hand; four of them is the longest wait.
    assert phy.airtime_ns(9, 500_000, 35) == 69_888_000 and longest_wait(9, 500_000, 35) == 279_552_000
    f = head({"hdr": 0x48, "hops": 31, "power": -4, "next": 0x01020304, "destination": 0xA0B0C0D0})
    assert f.hex() == "481ffc01020304a0b0c0d0"
    assert accepted(f + bytes(12)) and not accepted(f + bytes(3))
    # SF9 demodulates down to -12.5 dB. Sent at 2 dBm and heard at +11.5 dB, a frame was 24 dB
    # louder than it needed to be: its sender is reached at -22 dBm, and with the margin at -12.
    assert needs(2, 46, 9, -9, 22) == -9 and needs(2, 46, 9, -20, 22) == -12
    assert power(5, None, 2, 22) == 11 and power(5, 9, 0, 22) == 9 and power(20, None, 1, 22) == 22
    # At SF9 and 500 kHz a symbol is 1.024 ms, so a preamble of 16 and 13 more is 29.696 ms: a
    # bare preamble found at 5 ms holds a node until 34.696 ms, and a header for a 255-byte frame.
    assert head_wait(9, 500_000) == 29_696_000
    bare, whole = [(5_000_000, "preamble")], [(5_000_000, "preamble"), (9_000_000, "header")]
    assert receiving(9, 500_000, bare, 34_695_999) and not receiving(9, 500_000, bare, 34_696_000)
    assert receiving(9, 500_000, whole, 34_696_000) and not receiving(9, 500_000, bare, 4_999_999)
    assert not receiving(9, 500_000, whole + [(60_000_000, "end")], 60_000_000)
    # A header 40 ms after that preamble comes when its wait has run out, and so is held from
    # itself: a 255-byte frame is on the air 320.768 ms, which from the preamble ends at 325.768.
    late = bare + [(45_000_000, "header")]
    assert phy.airtime_ns(9, 500_000, 255) == 320_768_000
    assert receiving(9, 500_000, late, 325_768_000) and not receiving(9, 500_000, late, 365_768_000)


def ack_next(hops, leaf, nearest, source, routes, selected):
    """Where a message's destination sends its acknowledgement: the neighbour, or None. routes are
    the routes it holds to the message's source, selected the index of the one selected or None,
    and nearest a leaf's nearest relay, if it takes default routes, or None."""
    chosen = routes[selected]["next"] if selected is not None else None
    if chosen is None and leaf and nearest is not None:
        chosen = nearest  # a default route is a route
    if chosen is not None and not (chosen == source and hops < HOP_MAX):
        return chosen
    around = sorted((r["metric"], r["next"]) for r in routes
                    if r["relay"] and r["usable"] and r["next"] != source)
    if around:
        assert len(around) == 1 or around[0][0] != around[1][0], "the vectors leave no tie to break"
        return around[0][1]
    if leaf and nearest is not None:
        return nearest
    return chosen


def retry_next(heard, last, leaf, nearest, routes, selected):
    """Where a source's next try goes first: the route it has, if its last try was heard at its
    first hop `last`; if not, the lowest route through another neighbour it may use, feasible or
    not, then a leaf's nearest relay other than `last` (nearest, or None), then the route it has."""
    chosen = routes[selected]["next"] if selected is not None else nearest if leaf else None
    if heard:
        return chosen
    around = sorted((r["metric"], r["next"]) for r in routes if r["usable"] and r["next"] != last)
    if around:
        assert len(around) == 1 or around[0][0] != around[1][0], "the vectors leave no tie to break"
        return around[0][1]
    if leaf and nearest is not None:
        return nearest
    return chosen


def attributed_ack(sent, heard):
    """Whom an acknowledgement heard, after this node sent the message `sent`, is a worse sample
    of: the message's next hop, if that was its destination and the acknowledgement has the
    message's tag and HOP_MAX hops; otherwise no one."""
    s, h = head_of(sent), head_of(heard)
    return ("next" if heard[0] == 0x50 and h["hops"] == HOP_MAX and s["next"] == s["destination"]
            and sent[HEAD:HEAD + TAG] == heard[HEAD:HEAD + TAG] else None)


def head_of(frame):
    hdr, hops, power, nxt, destination = struct.unpack(">BBbII", frame[:HEAD])
    return {"hdr": hdr, "hops": hops, "power": power, "next": nxt, "destination": destination}


def build():
    self_check()
    heads = []
    for h, body in [
        ({"hdr": 0x48, "hops": 32, "power": 22, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x30, 0x30 + 4 + 5 + 8))),
        ({"hdr": 0x48, "hops": 1, "power": -9, "next": 1, "destination": 0xFFFFFFFE},
         bytes(range(0x80, 0x80 + 4 + 8))),
        ({"hdr": 0x49, "hops": 32, "power": 14, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x30, 0x30 + 4 + 20 + 8))),
        ({"hdr": 0x50, "hops": 31, "power": 0, "next": 0x0A0B0C0D, "destination": 0x1D2E3F40},
         bytes(range(0x30, 0x34)) + bytes.fromhex("c0ffee01")),
        ({"hdr": 0x51, "hops": 32, "power": 14, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x30, 0x30 + 4 + 4 + 37))),
        ({"hdr": 0x52, "hops": 30, "power": 2, "next": 0x0A0B0C0D, "destination": 0x30313233},
         bytes(range(0x40, 0x40 + 4 + 45))),
        ({"hdr": 0x53, "hops": 32, "power": 22, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes(range(0x50, 0x50 + 4 + 65))),
        ({"hdr": 0x54, "hops": 2, "power": -9, "next": 0x30313233, "destination": 0x30313233},
         bytes(range(0x60, 0x60 + 4 + 9))),
        ({"hdr": 0x56, "hops": 32, "power": 14, "next": 0x1D2E3F40, "destination": 0x0A0B0C0D},
         bytes.fromhex("c0ffee02") + struct.pack(">I", 0x30313233)),
        ({"hdr": 0x56, "hops": 30, "power": 8, "next": 0x0A0B0C0D, "destination": 0x0A0B0C0D},
         bytes.fromhex("c0ffee02") + struct.pack(">I", 0x30313233) + entry(0x1D2E3F40, 33)
         + entry(0x2A4A0644, -50)),
        ({"hdr": 0x57, "hops": 32, "power": 11, "next": 0x2A4A0644, "destination": 0x30313233},
         bytes.fromhex("c0ffee02") + bytes([0, 3]) + entry(0x1D2E3F40, 33) + entry(0x2A4A0644, -50)
         + entry(0x0A0B0C0D, 4)),
        ({"hdr": 0x57, "hops": 31, "power": 2, "next": 0x30313233, "destination": 0x30313233},
         bytes.fromhex("c0ffee03") + bytes([1, 1]) + entry(0x1D2E3F40, -128) + entry(0x2A4A0644, 127)),
    ]:
        frame = head(h) + body
        assert accepted(frame)
        heads.append({**h, "tag": body[:TAG].hex(), "frame": frame.hex()})

    good = {"hdr": 0x48, "hops": 32, "power": 14, "next": 7, "destination": 9}
    rejected = []
    for why, frame in [
        ("shorter than a head and a tag", head(good) + bytes(3)),
        ("a message with a tag and no check", head(good) + bytes(4)),
        ("a message a byte short of its check", head(good) + bytes(11)),
        ("not a frame of this section's", head({**good, "hdr": 0x59}) + bytes(12)),
        ("a message for the node a byte short of its check", head({**good, "hdr": 0x49}) + bytes(11)),
        ("a message with a reserved flag", head({**good, "hdr": 0x4A}) + bytes(12)),
        ("an acknowledgement too long", head({**good, "hdr": 0x50}) + bytes(9)),
        ("an acknowledgement too short", head({**good, "hdr": 0x50}) + bytes(7)),
        ("for every neighbour", head({**good, "next": 0xFFFFFFFF}) + bytes(12)),
        ("for neighbour zero", head({**good, "next": 0}) + bytes(12)),
        ("for destination zero", head({**good, "destination": 0}) + bytes(12)),
        ("for every destination", head({**good, "destination": 0xFFFFFFFF}) + bytes(12)),
        ("a first message_1 a byte long", head({**good, "hdr": 0x51}) + bytes(46)),
        ("a first message_1 with no routing id it came from", head({**good, "hdr": 0x51}) + bytes(41)),
        ("a first-contact message_2 a byte short", head({**good, "hdr": 0x52}) + bytes(48)),
        ("a first-contact message_3 of message_2's length", head({**good, "hdr": 0x53}) + bytes(49)),
        ("a first-contact message_4 a byte long", head({**good, "hdr": 0x54}) + bytes(14)),
        ("a first-contact message_4 for neighbour zero", head({**good, "hdr": 0x54, "next": 0}) + bytes(13)),
        ("first contact has no message_5", head({**good, "hdr": 0x55}) + bytes(13)),
        ("a trace with no routing id it came from", head({**good, "hdr": 0x56}) + bytes(4)),
        ("a trace a byte short of its routing id", head({**good, "hdr": 0x56}) + bytes(7)),
        ("a trace with part of an entry", head({**good, "hdr": 0x56}) + bytes(8 + 4)),
        ("a trace with 17 entries", head({**good, "hdr": 0x56}) + bytes(8 + 17 * ENTRY)),
        ("a trace answer with no out", head({**good, "hdr": 0x57}) + bytes(5)),
        ("a trace answer with more out than entries",
         head({**good, "hdr": 0x57}) + bytes(4) + bytes([0, 2]) + bytes(ENTRY)),
        ("a trace answer with a reserved flag",
         head({**good, "hdr": 0x57}) + bytes(4) + bytes([3, 1]) + bytes(ENTRY)),
        ("a trace answer with 17 entries back",
         head({**good, "hdr": 0x57}) + bytes(4) + bytes([0, 1]) + bytes(18 * ENTRY)),
        ("a trace for every destination",
         head({**good, "hdr": 0x56, "destination": 0xFFFFFFFF}) + bytes(8)),
    ]:
        assert not accepted(frame)
        rejected.append({"why": why, "frame": frame.hex()})

    tag, other = bytes.fromhex("30313233"), bytes.fromhex("40414243")
    body = tag + bytes(range(0x60, 0x6D))  # the tag, five bytes of message and the check

    def message(hops, destination=9, rest=body, nxt=7, pw=14, hdr=0x48):
        return head({"hdr": hdr, "hops": hops, "power": pw, "next": nxt, "destination": destination}) + rest

    def ack(hops, destination=77, t=tag, nxt=7):
        return head({"hdr": 0x50, "hops": hops, "power": 3, "next": nxt, "destination": destination}) + t + bytes(4)

    def trace(hops, ents=(), destination=9, nxt=7, source=77):
        h = {"hdr": HDR_TRACE, "hops": hops, "power": 5, "next": nxt, "destination": destination}
        return head(h) + tag + struct.pack(">I", source) + b"".join(entry(r, q) for r, q in ents)

    def trace_answer(hops, ents, out, flags=0, destination=77, nxt=7, t=tag):
        h = {"hdr": HDR_ANSWER, "hops": hops, "power": 5, "next": nxt, "destination": destination}
        return head(h) + t + bytes([flags, out]) + b"".join(entry(r, q) for r, q in ents)

    def contact(n, hops, destination=9, nxt=7, fill=0x70):
        h = {"hdr": 0x50 + n, "hops": hops, "power": 6, "next": nxt, "destination": destination}
        return head(h) + tag + bytes(range(fill, fill + CONTACT_LEN[0x50 + n] - HEAD - TAG))

    hops = []
    for why, s, h in [
        ("passed on", message(20), message(19, nxt=8, pw=-2)),
        ("another copy of what it sent", message(20), message(20)),
        ("passed on twice: not by its neighbour", message(20), message(18)),
        ("another tag", message(20), message(19, rest=other + body[4:])),
        ("the same tag and another message", message(20), message(19, rest=tag + bytes(13))),
        ("the same tag and a longer message", message(20), message(19, rest=body + b"\x00")),
        ("for another node", message(20), message(19, destination=10)),
        ("a message for the node, passed on", message(20, hdr=0x49), message(19, nxt=8, hdr=0x49)),
        ("a message for the node, acknowledged", message(20, hdr=0x49), ack(32)),
        ("the same bytes as a message for the user: another frame", message(20, hdr=0x49), message(19)),
        ("acknowledged", message(20), ack(32)),
        ("acknowledged by the node it went to: still no sample", message(20, nxt=77), ack(32, nxt=7)),
        ("acknowledged, heard further off", message(20), ack(5)),
        ("another message acknowledged", message(20), ack(32, t=other)),
        ("an acknowledgement passed on", ack(20, destination=9), ack(19, destination=9, nxt=8)),
        ("an acknowledgement is not ended by a message", ack(20, destination=9), message(19)),
        ("hops do not wrap", message(0), message(255)),
        ("first contact passed on", contact(1, 20), contact(1, 19, nxt=8)),
        ("first contact, another copy of what it sent", contact(3, 20), contact(3, 20)),
        ("first contact, another message with the same tag", contact(2, 20), contact(2, 19, fill=0x71)),
        ("first contact is not ended by an acknowledgement with its tag", contact(1, 20), ack(32)),
        ("first contact is not ended by its answer", contact(1, 20), contact(2, 32, destination=77)),
        ("a message is not ended by first contact with its tag", message(20), contact(4, 19)),
        ("a trace passed on, its entry added", trace(20), trace(19, [(8, 12)], nxt=9)),
        ("a trace passed on with no entry added", trace(20), trace(19, nxt=9)),
        ("a trace passed on with two entries added", trace(20), trace(19, [(8, 12), (9, 3)], nxt=9)),
        ("a trace passed on, an entry before changed", trace(20, [(5, 8)]),
         trace(19, [(5, 9), (8, 12)], nxt=9)),
        ("a trace answered", trace(20, nxt=9), trace_answer(32, [(9, 40)], 1, destination=77)),
        ("a trace answered by a keeper", trace(20), trace_answer(32, [(8, 40)], 1, flags=1, destination=77)),
        ("another trace answered", trace(20), trace_answer(32, [(9, 40)], 1, t=other, destination=77)),
        ("a trace is not ended by an acknowledgement with its tag", trace(20), ack(32)),
        ("a message is not ended by a trace answer with its tag", message(20), trace_answer(32, [(9, 4)], 1)),
        ("a trace answer passed on, its entry added", trace_answer(20, [(9, 40)], 1),
         trace_answer(19, [(9, 40), (6, -4)], 1, nxt=8)),
        ("a trace answer is not ended by another answer", trace_answer(20, [(9, 40)], 1),
         trace_answer(32, [(9, 40)], 1, nxt=8)),
    ]:
        assert accepted(s) and accepted(h)
        assert ends(s, h) or not teaches(s, h)
        hops.append({"why": why, "sent": s.hex(), "heard": h.hex(), "ends": ends(s, h),
                     "teaches": teaches(s, h)})

    waits = []
    for why, f in [
        ("a message", message(20)),
        ("a message to its destination: its acknowledgement is listened for", message(20, nxt=9)),
        ("a message for the node, to its destination", message(20, nxt=9, hdr=0x49)),
        ("an acknowledgement on its way", ack(20)),
        ("an acknowledgement to the node it is for", ack(20, nxt=77)),
        ("first contact on its way", contact(1, 32)),
        ("first contact to the node it is for", contact(1, 32, nxt=9)),
        ("the last frame of first contact to the node it is for", contact(4, 3, nxt=9)),
        ("the last frame of first contact on its way", contact(4, 3)),
        ("a trace on its way", trace(32)),
        ("a trace to its destination: its answer is listened for", trace(32, nxt=9)),
        ("a trace answer on its way", trace_answer(32, [(9, 4)], 1)),
        ("a trace answer to the node that began the trace", trace_answer(30, [(9, 4)], 1, nxt=77)),
    ]:
        assert accepted(f)
        waits.append({"why": why, "sent": f.hex(), "listens": hop_heard(f)})

    # A relay passing a trace or an answer on, and a node answering one. Routing ids are small here
    # but for the last case, so the entries are easy to read.
    full_trace = trace(20, [(100 + i, i) for i in range(TRACE_ENTRIES)], nxt=8)
    full_back = trace_answer(20, [(9, 4)] + [(100 + i, i) for i in range(TRACE_ENTRIES)], 1, nxt=8)
    entries = []
    for why, f, rid, q in [
        ("a trace with no entries", trace(32, nxt=8), 8, 12),
        ("a trace with two", trace(30, [(5, 20), (6, -7)], nxt=8), 8, -33),
        ("a signal-to-noise ratio above what an entry holds", trace(30, nxt=8), 8, 300),
        ("one below it", trace(30, nxt=8), 8, -300),
        ("a trace with one hop left: not passed on", trace(1, nxt=8), 8, 12),
        ("a trace with no hops left", trace(0, nxt=8), 8, 12),
        ("a trace that already holds as many entries as it may", full_trace, 8, 12),
        ("one entry short of it", trace(20, [(100 + i, i) for i in range(TRACE_ENTRIES - 1)], nxt=8), 8, 12),
        ("an answer on its way back", trace_answer(29, [(5, 20), (9, 4)], 2, nxt=8), 8, 16),
        ("an answer with as many entries back as it may", full_back, 8, 16),
        ("an answer with a full way out and none back",
         trace_answer(29, [(100 + i, i) for i in range(TRACE_ENTRIES)], TRACE_ENTRIES, nxt=8), 8, 16),
    ]:
        assert accepted(f)
        out = pass_on(f, rid, q)
        if out is not None:
            assert accepted(f[:1] + bytes([out[0]]) + f[2:AT_DEST] + out[1])
            assert ends(f, f[:1] + bytes([out[0]]) + f[2:AT_DEST] + out[1])
        entries.append({"why": why, "frame": f.hex(), "id": rid, "snr_quarter_db": q,
                        "hops": None if out is None else out[0],
                        "passed": None if out is None else out[1].hex()})

    answers = []
    for why, f, rid, q, flags in [
        ("by its destination, with no relay on the way", trace(32, nxt=9), 9, 40, 0),
        ("by its destination, through two relays", trace(30, [(5, 20), (6, -7)], nxt=9), 9, 40, 0),
        ("by the keeper of its destination, asleep", trace(31, [(5, 20)], nxt=6), 6, -2, 1),
        ("by a relay with no route to it", trace(31, [(5, 20)], nxt=6), 6, 3, 2),
        ("with a routing id of every bit", trace(32, [(0xFFFFFFFE, 1)], destination=0xA1B2C3D4,
         nxt=0xA1B2C3D4, source=0x80000001), 0xA1B2C3D4, 7, 0),
        ("a trace too full to answer", trace(20, [(100 + i, i) for i in range(TRACE_ENTRIES)], nxt=9), 9, 40, 0),
    ]:
        assert accepted(f)
        a = answer(f, rid, q, flags)
        if a is not None:
            assert accepted(bytes([HDR_ANSWER, HOP_MAX, 0, 0, 0, 0, 1]) + a)
            assert ends(f, bytes([HDR_ANSWER, HOP_MAX, 0, 0, 0, 0, 1]) + a)
        answers.append({"why": why, "frame": f.hex(), "id": rid, "snr_quarter_db": q,
                        "as": ["destination", "keeper", "no route"][flags],
                        "answer": None if a is None else a.hex()})

    backs = [
        {
            "power": p, "snr_quarter_db": q, "spreading_factor": sf, "lowest": lo, "full": hi,
            "needs": needs(p, q, sf, lo, hi),
        }
        for p, q, sf, lo, hi in [
            (2, 46, 9, -9, 22), (2, 46, 9, -20, 22), (22, -50, 9, -9, 22), (22, -49, 9, -9, 22),
            (22, -47, 9, -9, 20), (14, 3, 7, -9, 22), (-9, 127, 7, -9, 22), (10, -30, 7, -9, 14),
            (0, 1, 12, -9, 22),
        ]
    ]

    powers = [
        {"neighbour": n, "back": b, "try": t, "full": hi, "power": power(n, b, t, hi)}
        for n, b, t, hi in [
            (5, None, 0, 22), (5, None, 1, 22), (5, None, 2, 22), (5, 9, 0, 22), (5, 9, 2, 22),
            (9, 5, 0, 22), (20, None, 1, 22), (-9, -9, 0, 22), (22, None, 2, 22), (12, 14, 1, 14),
        ]
    ]

    # A frame sent again waits a random time, so a case can give only its bound: the least and
    # the largest frames, and one between, on each profile and on the slowest setting, for a hop
    # sent again and for a message started again by its source.
    agains = [
        {
            "again": which, "spreading_factor": sf, "bandwidth_hz": bw, "length": n,
            "airtime_ns": phy.airtime_ns(sf, bw, n), "longest_ns": longest_wait(sf, bw, n),
        }
        for sf, bw in [(9, 500_000), (7, 125_000), (12, 125_000)]
        for which, lengths in [("hop", (ACK_LEN, MESSAGE_MIN, 35, 255)), ("source", (MESSAGE_MIN, 35, 255))]
        for n in lengths
    ]

    listens = [c for sf, bw in [(9, 500_000), (7, 125_000), (12, 125_000)] for c in listen_cases(sf, bw)]

    source, desk_relay, other_relay = 0x0A0B0C0D, 0x1D2E3F40, 0x2A4A0644

    def rt(nxt, relay, usable, feasible, metric):
        return {"next": nxt, "relay": relay, "usable": usable, "feasible": feasible,
                "metric": metric}

    direct = rt(source, False, True, True, 70)
    via = rt(desk_relay, True, True, False, 140)
    via_far = rt(other_relay, True, True, False, 210)
    acked = []
    for why, hops_at, leaf, nearest, routes, selected in [
        ("the field test's: direct selected, the message passed on by a relay", 31, False, None,
         [direct, via], 0),
        ("the message came direct: the selected route", 32, False, None, [direct, via], 0),
        ("of two relays, the lower metric", 30, False, None, [direct, via_far, via], 0),
        ("no relay to go by: direct as before", 31, False, None, [direct], 0),
        ("a relay it may not use is not gone by", 31, False, None,
         [direct, rt(desk_relay, True, False, False, 140)], 0),
        ("the selected route is through a relay already", 31, False, None,
         [rt(desk_relay, True, True, True, 140), rt(other_relay, True, True, True, 70)], 0),
        ("no route selected: an infeasible one through a relay", 31, False, None,
         [rt(source, False, False, True, 70), via], None),
        ("no route selected and none through a relay: none", 31, False, None,
         [rt(source, False, False, True, 70)], None),
        ("as a leaf: a relay's route held", 31, True, other_relay, [direct, via], 0),
        ("as a leaf with none: its nearest relay", 31, True, other_relay, [direct], 0),
        ("as a leaf with no route selected: its default route", 31, True, other_relay,
         [rt(source, False, False, True, 70), via], None),
        ("as a leaf that takes no default route: direct", 31, True, None, [direct], 0),
    ]:
        acked.append({"why": why, "hops": hops_at, "leaf": leaf, "nearest": nearest,
                      "source": source, "routes": routes, "selected": selected,
                      "next_after": ack_next(hops_at, leaf, nearest, source, routes, selected)})

    leafward = rt(source, False, True, True, 70)  # here the destination, a leaf neighbour
    retried = []
    for why, heard_, leaf, nearest, routes, selected in [
        ("the field test's: direct, unheard; through a relay, infeasible", False, False, None,
         [leafward, via], 0),
        ("heard at its first hop: the same way again", True, False, None, [leafward, via], 0),
        ("of two others, the lower metric", False, False, None, [leafward, via_far, via], 0),
        ("no other way: the same", False, False, None, [leafward], 0),
        ("another it may not use is not gone by", False, False, None,
         [leafward, rt(desk_relay, True, False, False, 140)], 0),
        ("through a relay, unheard: direct to the destination", False, False, None,
         [rt(desk_relay, True, True, True, 140), leafward], 0),
        ("as a leaf with none: its nearest relay", False, True, other_relay, [leafward], 0),
        ("as a leaf that takes no default route: the same", False, True, None, [leafward], 0),
    ]:
        last = routes[selected]["next"]
        retried.append({"why": why, "heard": heard_, "last": last, "leaf": leaf,
                        "nearest": nearest, "routes": routes, "selected": selected,
                        "next_after": retry_next(heard_, last, leaf, nearest, routes, selected)})

    msg_to = lambda nxt, dest: head({"hdr": 0x48, "hops": 31, "power": 14, "next": nxt,
                                     "destination": dest}) + body
    ack_of = lambda hops_, t=tag: head({"hdr": 0x50, "hops": hops_, "power": 10, "next": 77,
                                        "destination": 77}) + t + bytes(4)
    attributed = []
    for why, sent, heard in [
        ("its destination's acknowledgement, made there", msg_to(9, 9), ack_of(HOP_MAX)),
        ("passed on since: anyone's", msg_to(9, 9), ack_of(HOP_MAX - 1)),
        ("the message went on beyond its next hop", msg_to(7, 9), ack_of(HOP_MAX)),
        ("another message's tag", msg_to(9, 9), ack_of(HOP_MAX, other)),
    ]:
        attributed.append({"why": why, "sent": sent.hex(), "heard": heard.hex(),
                           "from": attributed_ack(sent, heard)})
    for hops_at in (HOP_MAX, HOP_MAX - 1, 1):
        attributed.append({"why": "a message for this node, made by its source" if hops_at ==
                           HOP_MAX else "a message for this node, passed on",
                           "hops": hops_at, "from": "source" if hops_at == HOP_MAX else None})

    return {
        "description": "Frames that follow routes, draft 0 (draft/forwarding.md). Routing ids "
        "are numbers; frames and tags are hex. In hops, sent is the frame the node sent and "
        "heard the one it then received; ends is whether that ends the hop, and teaches whether the "
        "node takes it as a sample of its neighbour's floor. In waits, listens is whether a node that has sent the "
        "frame listens for its hop to succeed, and sends it again if it does not. In entries, a relay "
        "with routing id id receives the trace or trace answer frame, for it, heard at "
        "snr_quarter_db, and passes on a frame whose hops is hops and whose bytes from destination "
        "on are passed, or drops it where passed is null. In answers, the node id receives the "
        "trace frame, heard at snr_quarter_db, as its destination, the keeper of its destination "
        "asleep, or a relay with no route to it (as), and answers with a trace answer whose bytes "
        "from destination on are answer, or drops it where answer is null. In backs, power is what a frame was sent at in dBm and "
        "snr_quarter_db what it was heard at, and needs is what an answer must go at for its "
        "sender to hear it, between the node's lowest and full power. In powers, neighbour is "
        "what Routes gives for the neighbour, its boost included, back is what the node the "
        "frame came from needs or null for a frame that answers none, and try counts from 0. In "
        "agains, a frame of length bytes is sent again at that spreading factor and bandwidth, "
        "with the profiles' preamble and coding rate (vectors/phy.json), by a hop that heard "
        "nothing of it (hop) or by its source with no acknowledgement (source): airtime_ns is "
        "its time on the air and longest_ns the longest it may wait first. In listens, a radio at "
        "that spreading factor and bandwidth finds a preamble or a header, says a frame has ended "
        "(end), or is given a frame to send (sent) at the times in events, and receiving is "
        "whether a node may not start to send at each time in asks, every event at or before "
        "that time having happened. In acknowledged, a message arrived with hops at its "
        "destination, a leaf or not, whose nearest relay is nearest if it is a leaf that takes "
        "default routes (null for none); routes are the routes it holds to the message's source, "
        "each through the neighbour next, a relay or not, that it may use or not, feasible or not, "
        "with its metric, and selected the index of the one selected (null for none); next_after "
        "is the neighbour it sends the acknowledgement to (null for none). In retried, a source holds "
        "routes to its message's destination as in acknowledged, its last try having gone first "
        "to last and been heard there or not; next_after is where its next try goes first. In "
        "attributed, a node sent the message sent and then received the acknowledgement heard, and "
        "takes a worse sample of the message's next hop (from next) or of no one (null); or, as "
        "the destination of a message it accepts that arrived with hops, of its source (source) or "
        "of no one.",
        "generator": "vectors/tools/forwarding.py",
        "heads": heads,
        "rejected": rejected,
        "hops": hops,
        "waits": waits,
        "entries": entries,
        "answers": answers,
        "backs": backs,
        "powers": powers,
        "agains": agains,
        "listens": listens,
        "acknowledged": acked,
        "retried": retried,
        "attributed": attributed,
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
