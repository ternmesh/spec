#!/usr/bin/env python3
"""Generates and checks the radio-settings test vectors (draft/phy.md).

    python3 vectors/tools/phy.py generate   # rewrite vectors/phy.json
    python3 vectors/tools/phy.py check      # fail if the file differs from what this computes

Needs nothing outside the standard library. Before computing anything it checks its time-on-air
arithmetic against values worked by hand from Semtech's formula (SX1261/2 datasheet, section
6.1.4), and against the two frames whose times unicast-security.md quotes.

Like everything under vectors/, this file is dedicated to the public domain (CC0-1.0).
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "phy.json"

SYNC_WORD = 0x5E
PREAMBLE = 16
CODING_RATE = 1  # 4/5

# name, centre frequency, bandwidth, SF, radiated power limit (dBm EIRP), share of the window a
# node may transmit for (parts per million), the window (seconds).
PROFILES = [
    ("US915", 921_250_000, 500_000, 9, 36, 1_000_000, 3600),
    ("EU868", 869_475_000, 125_000, 7, 29, 100_000, 3600),
    ("AU915", 921_250_000, 500_000, 9, 30, 1_000_000, 3600),
    ("NZ915", 921_250_000, 500_000, 9, 36, 1_000_000, 3600),
]

# Frame lengths: the smallest unicast frame, the four first-contact frames, and the largest frame.
LENGTHS = [16, 17, 45, 53, 73, 255]


def sync_word_sx126x(byte):
    """The SX126x's two-byte form of a one-byte sync word: 0xXY becomes 0xX4Y4."""
    return (byte & 0xF0) << 8 | 0x0400 | (byte & 0x0F) << 4 | 0x04


def airtime_ns(sf, bw_hz, length, preamble=PREAMBLE, cr=CODING_RATE):
    """Time on air of an explicit-header frame with a CRC, to the nearest nanosecond."""
    ldro_on = ldro(sf, bw_hz)
    bits = 8 * length - 4 * sf + 28 + 16
    per_block = 4 * (sf - (2 if ldro_on else 0))
    blocks = -(-bits // per_block) if bits > 0 else 0
    symbols = 8 + blocks * (cr + 4)
    quarters = 4 * preamble + 17 + 4 * symbols  # the preamble is 4.25 symbols longer than set
    num, den = quarters * (1 << sf) * 1_000_000_000, 4 * bw_hz
    return (num + den // 2) // den


def ldro(sf, bw_hz):
    """Low data rate optimisation: on when a symbol lasts 16 ms or longer."""
    return (1 << sf) * 1000 >= bw_hz * 16


def must_refuse(sent, at_ns, air_ns, ppm, window_s):
    """Whether sending a frame of air_ns at at_ns would take some period of the window's length
    past the limit, given the (time, time on air) of what was sent before. Frames count by when
    they begin, and a period is closed where it starts and open where it ends."""
    window = window_s * 1_000_000_000
    limit = window // 1_000_000 * ppm
    frames = sent + [(at_ns, air_ns)]
    # Every period that matters begins with a frame.
    return any(
        sum(a for t, a in frames if start <= t < start + window) > limit
        for start, _ in frames
        if start <= at_ns < start + window
    )


def duty_cases(sf, bw, ppm, window_s):
    """Histories of frames sent, and a frame asked for after each: one the limit forbids, or one
    it does not. A node may hold a frame back longer than the limit needs, so only must_refuse
    true binds it."""
    s, air = 1_000_000_000, airtime_ns(sf, bw, 255)
    window = window_s * s
    most = (window // 1_000_000 * ppm) // air  # frames of 255 bytes the limit allows
    cases = []

    def case(why, runs, at):
        sent = [(first + i * s, air) for first, count in runs for i in range(count)]
        cases.append(
            {
                "why": why,
                "sent": [
                    {"first_at_ns": first, "count": count, "every_ns": s, "length": 255}
                    for first, count in runs
                ],
                "at_ns": at,
                "length": 255,
                "must_refuse": must_refuse(sent, at, air, ppm, window_s),
            }
        )

    half = most // 2
    case("nothing sent", [], 0)
    case("one frame short of the limit", [(0, most - 1)], most * s)
    case("at the limit", [(0, most)], most * s)
    case("at the limit, the first frame a nanosecond short of leaving the window", [(0, most)],
         window - 1)
    case("at the limit, as the first frame leaves the window", [(0, most)], window)
    # A node that counts by the clock's hours would start afresh at the hour.
    case("the limit used just before the hour, asked just after it", [(window - most * s, most)],
         window + s)
    case("the same, as the first of them leaves the window", [(window - most * s, most)],
         2 * window - most * s)
    # Half used at the end of one hour and half at the start of the next: each clock hour is
    # under the limit, and the hour across them is at it.
    case("the limit used across the hour", [(window - half * s, half), (window, most - half)],
         window + most * s)
    case("long silence after the limit", [(0, most)], 5 * window)
    assert [c["must_refuse"] for c in cases] == [
        False, False, True, True, False, True, False, True, False]
    return cases


def self_check():
    # By hand: SF7/125 kHz, 64 bytes, preamble 8: 528 bits in 19 blocks of 28, so
    # 12.25 + 8 + 19 * 5 = 115.25 symbols of 1.024 ms.
    assert airtime_ns(7, 125_000, 64, preamble=8) == 118_016_000
    # SF12/125 kHz with LDRO, 16 bytes, preamble 8: 124 bits in 4 blocks of 40, so
    # 12.25 + 8 + 4 * 5 = 40.25 symbols of 32.768 ms.
    assert airtime_ns(12, 125_000, 16, preamble=8) == 1_318_912_000
    # unicast-security.md: a 40-byte text at SF11/250 kHz is 682 ms with 16 bytes of overhead and
    # 764 ms with 28.
    assert round(airtime_ns(11, 250_000, 56) / 1e6) == 682
    assert round(airtime_ns(11, 250_000, 68) / 1e6) == 764
    assert sync_word_sx126x(0x2B) == 0x24B4 and sync_word_sx126x(0x12) == 0x1424
    assert sync_word_sx126x(0x34) == 0x3444


def build():
    self_check()
    profiles = []
    for name, freq, bw, sf, eirp, ppm, window in PROFILES:
        profiles.append(
            {
                "name": name,
                "frequency_hz": freq,
                "bandwidth_hz": bw,
                "spreading_factor": sf,
                "max_eirp_dbm": eirp,
                "duty_cycle_ppm": ppm,
                "duty_window_s": window,
                "low_data_rate_optimisation": ldro(sf, bw),
                "airtime_ns": [
                    {"length": n, "ns": airtime_ns(sf, bw, n)} for n in LENGTHS
                ],
                "duty": duty_cases(sf, bw, ppm, window) if ppm < 1_000_000 else [],
            }
        )
    return {
        "description": "Radio settings, draft 0 (draft/phy.md). An implementation MUST use "
        "sync_word, in the form its radio takes (sync_word_sx126x for the SX126x family), with "
        "preamble_symbols, coding rate 4/coding_rate_denominator, an explicit header and a CRC. "
        "For each profile it MUST use frequency_hz, bandwidth_hz and spreading_factor, and MUST "
        "compute, for a frame of each length, the time on air ns, in nanoseconds. It MUST NOT "
        "transmit for more than duty_cycle_ppm millionths of any duty_window_s seconds; "
        "1000000 means the profile sets no limit. sync_word and sync_word_sx126x are hex. Each "
        "case in duty gives frames already sent, as runs of count frames of length bytes, the "
        "first beginning at first_at_ns and each every_ns after the one before, and a frame "
        "asked for at at_ns: where must_refuse is true the node MUST NOT send it then; "
        "where it is false the limit does not forbid it, and a node may still hold it back.",
        "generator": "vectors/tools/phy.py",
        "sync_word": f"{SYNC_WORD:02x}",
        "sync_word_sx126x": f"{sync_word_sx126x(SYNC_WORD):04x}",
        "preamble_symbols": PREAMBLE,
        "coding_rate_denominator": CODING_RATE + 4,
        "explicit_header": True,
        "crc": True,
        "iq_inverted": False,
        "profiles": profiles,
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
