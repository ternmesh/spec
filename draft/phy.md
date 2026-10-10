# Radio settings

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Every value here is
**provisional**: chosen from published rules, published measurements and
other projects' sources, and not yet from measurements of Tern's own
(see [Not yet measured](#not-yet-measured)). It is not legal advice;
whoever operates a radio answers for it.

This section defines the LoRa settings every Tern frame is sent with,
and, for each region, the one channel and modulation a node uses to
find and be found: its **profile**. Until the specification has a MAC
that schedules links on other settings, a profile's channel carries
everything.

Test vectors: [`vectors/phy.json`](../vectors/phy.json), produced by
[`vectors/tools/phy.py`](../vectors/tools/phy.py).

## Goals

1. **Never mistaken for another network.** Radios of other LoRa
   networks discard Tern's frames in hardware, and Tern's discard
   theirs.
2. **Within each region's rules as they are written**, not as they are
   commonly read. In the US that means 500 kHz.
3. **Out of the way.** Where a band has room, a profile's channel
   avoids the channels other networks use by default.
4. **Where the simulation was run.** A profile's modulation is the one,
   or the equal of the one, that the routing design was measured at.
5. **One answer for time on air.** Every implementation computes the
   same time on air for a frame, to the nanosecond, because the airtime
   budget and the routing metric are both measured in it.

## Settings every frame uses

| | |
|---|---|
| Modulation | LoRa |
| Sync word | `0x5E` |
| Preamble | 16 symbols |
| Header | explicit |
| CRC | on |
| Coding rate | 4/5 |
| IQ | not inverted |
| Low data rate optimisation | on if a symbol lasts 16 ms or longer, otherwise off |

The sync word is given in the one-byte form that the SX127x family
takes. A radio of the SX126x family takes two bytes, and the one-byte
form `0xXY` is `0xX4Y4` there, so Tern's is `0x54E4`. An implementation
MUST use the form that puts the same two symbols on the air.

A frame is at most 255 bytes. Its first byte, `hdr`, says what it is
([unicast](unicast-security.md#the-frame),
[first contact](first-contact.md#the-frame)); a node MUST NOT rely on
the sync word alone to tell that a frame is Tern's.

## Time on air

With `SF` the spreading factor, `BW` the bandwidth in hertz, `L` the
frame's length in bytes and `DE` 1 if low data rate optimisation is on
and 0 otherwise:

```
blocks   = max(ceil((8 L - 4 SF + 44) / (4 (SF - 2 DE))), 0)
symbols  = 16 + 4.25 + 8 + 5 blocks
airtime  = symbols * 2^SF / BW   seconds
```

An implementation MUST compute it without floating point and round once,
to the nearest nanosecond.

## Profiles

A node is set to one profile. It MUST send and listen on the profile's
frequency, with its bandwidth and spreading factor.

| Profile | Frequency | Bandwidth | SF | Radiated power, at most | Transmitting, at most |
|---|---|---|---|---|---|
| `US915` | 921.250 MHz | 500 kHz | 9 | 36 dBm EIRP | no limit |
| `EU868` | 869.475 MHz | 125 kHz | 7 | 29 dBm EIRP | 10% of any hour |
| `AU915` | 921.250 MHz | 500 kHz | 9 | 30 dBm EIRP | no limit |
| `NZ915` | 921.250 MHz | 500 kHz | 9 | 36 dBm EIRP | no limit |

**Power.** A node MUST NOT radiate more than its profile allows, antenna
gain included. `US915` also limits what the transmitter may put into the
antenna, to 30 dBm.

**Transmitting.** Where a profile limits it, the time on air of all a
node's transmissions that begin in any period of the length given MUST
NOT exceed that share of the period. A node that would exceed it by
sending a frame MUST NOT send the frame until it would not. A period
includes the instant it starts at and not the instant it ends at. This is the
regulator's limit, the same for every node. The airtime budget, which
divides the channel between nodes, is a separate and smaller allowance,
and is not specified yet.

## Conformance

An implementation conforms to this section if, for
[`vectors/phy.json`](../vectors/phy.json):

* it uses `sync_word`, as `sync_word_sx126x` on a radio of that family,
  with `preamble_symbols`, coding rate 4/`coding_rate_denominator`, a
  header that is explicit or not as `explicit_header` says, a CRC or
  not as `crc` says, and IQ inverted or not as `iq_inverted` says;
* for each profile it implements, it uses `frequency_hz`, `bandwidth_hz`
  and `spreading_factor`, with low data rate optimisation on or off as
  `low_data_rate_optimisation` says;
* for each profile and each `length`, it computes the time on air `ns`;
* given the times at which it is asked to send frames, it sends none
  that would take its time on air past `duty_cycle_ppm` millionths of
  any `duty_window_s` seconds: for each case in a profile's `duty`,
  having sent the frames in `sent`, it does not send the frame asked
  for at `at_ns` if `must_refuse` is true. Where it is false the limit
  does not forbid the frame; a node may still hold it back, since
  nothing here obliges it to send.

That two radios set this way hear each other, and that radios of other
networks do not hear them, cannot be checked by vectors. It is checked
on hardware.

## Rationale

**Sync word `0x5E`.** In use already are `0x12` (LoRa's "private"
default, MeshCore, Reticulum's RNode and most hobby code), `0x34`
(LoRaWAN), `0x2B` (Meshtastic) and `0x14` (Meshtastic's oldest
releases), each read from the project's source. Each half of the byte
becomes one symbol after the preamble. A receiver may accept a symbol
one step from the one it expects, and a zero looks like more preamble,
so each half of Tern's is at least two steps from every half in use,
and neither is zero. `0x67` is the alternate if `0x5E` proves a poor
choice on some radio; Meshtastic's `0x2B` shows that a half above 8
works across the SX127x, SX126x and LR11x0.

**A sync word is a filter, not a wall.** Other networks' frames still
arrive as energy, and trip channel-activity detection. So a frame says
what it is in its first byte as well.

**A 16-symbol preamble** gives a receiver that has just finished
sending, or has just woken, time to lock, and is what Meshtastic and
MeshCore both use. It costs 8 symbols over the radio's default: about
8 ms a frame at either profile.

**`US915`: 500 kHz, because the rules say so.** 47 CFR 15.247 offers a
radio on 902–928 MHz two ways to exceed a milliwatt. As a digitally
modulated system, (a)(2), its 6 dB bandwidth must be at least 500 kHz,
and then there is no limit on how long or how often it transmits. As a
frequency hopper, (a)(1), it must hop over at least 25 or 50 channels
and dwell no more than 0.4 s on each. A fixed channel 125 or 250 kHz
wide is neither. LoRa at 500 kHz is the first; LoRaWAN's own 500 kHz
channels in the band are certified that way. Meshtastic's and
MeshCore's long-standing US defaults were narrower, and both
communities began moving to 500 kHz in 2026.

**`US915`: SF9.** At 500 kHz, SF9 has the sensitivity of SF7 at 125 kHz
within a decibel (four times the noise bandwidth is 6 dB, and two steps
of spreading factor win back 5 dB), and slightly less time on air
(121 ms against 152 ms for first contact's largest frame). SF7 at
125 kHz is the setting at which the simulator
([ternmesh/sim](https://github.com/ternmesh/sim)) compared routing
designs over a thousand nodes, and at which Tern's delivered 89 to 97%
of unicast messages on time at 0 dBm and above, against 53% at best for
the others. At the slow settings existing meshes run, every design it
tried was overloaded.

**`US915`: 921.250 MHz.** LoRaWAN's US plan sends uplinks on
902.3–914.9 MHz and downlinks on 923.3–927.5 MHz (RP002, section 2.5),
which leaves 915.2 to 923.0 MHz free of both. Within that, the channel
is clear of the frequencies Meshtastic's presets fall on by default
(906.875, 908.750, 913.125, 918.875, 925.250 and 926.750 MHz, from its
published slot rule) and of MeshCore's US preset (910.525 MHz). It lies
on Meshtastic's grid of 500 kHz slots, so that it overlaps one slot a
Meshtastic network could be moved to, not half of each of two.

**`EU868`: the one sub-band there is.** 869.40–869.65 MHz allows 500 mW
ERP at a 10% duty cycle (ERC Recommendation 70-03, Annex 1; EN 300 220-2). Every other sub-band at 868 MHz allows 25 mW at 1% or
0.1%, which a relay cannot live on: in the simulator, every design
collapsed at 1%. The sub-band is 250 kHz wide, so Meshtastic
(869.525 MHz, 250 kHz) and MeshCore (869.618 MHz, 62.5 kHz) are already
in it, and nothing can avoid both. A 125 kHz channel at 869.475 MHz
stays 12.5 kHz inside the lower edge, misses MeshCore's channel by
50 kHz, and overlaps half of Meshtastic's.

**`EU868`: SF7 at 125 kHz** is the simulator's setting itself.

**`AU915` and `NZ915`: `US915`'s channel and modulation.** Australia's
class licence for low interference potential devices (2025, Schedule 1,
Table 8, item 6 and clause 43) allows a digitally modulated transmitter
1 W EIRP anywhere in 915–928 MHz, if its radiated peak power spectral
density is at most 25 mW in any 3 kHz. New Zealand's general user
licence for short range devices (2022, notice 2022-go3100) allows 0 dBW
EIRP in 915–928 MHz, and 6 dBW in 920–928 MHz to a transmitter that
uses digital modulation (special condition 13). Neither has a floor on
bandwidth or a limit on transmitting, so either could take a narrower
channel; the one `US915` uses serves both, for three reasons:

* At 30 dBm, 500 kHz puts about 6 mW in 3 kHz, a quarter of
  Australia's limit; 125 kHz would put 24 mW there, at it.
* 921.250 MHz lies in 920–928 MHz, where New Zealand allows 6 dB more,
  and below 923.05 MHz, where LoRaWAN's AU915 downlinks begin (RP002).
  The uplink channels it overlaps, 921.0 to 921.4 MHz, are in the
  plan's fourth sub-band, not the second (916.8–918.2 MHz) that The
  Things Network and most networks in Australia use. Meshtastic's `ANZ` presets fall, by the
  same slot rule as in the US, at 915.6875, 918.3125, 918.875, 919.875,
  920.625, 921.750, 926.125, 926.750 and 927.875 MHz, and the nearest of
  them, 500 kHz wide, begins where this channel ends. MeshCore's
  Australian presets sit near 915.8 MHz.
* A board built for the 915 MHz band works in all three countries on the
  same channel, so it does not need a fourth.

They are two profiles, not one, because what each country allows a node
to radiate is different, and a node in New Zealand would lose 6 dB to
Australia's limit.

**Radiated power, as EIRP.** 500 mW ERP is 27 dBm ERP, which is 29 dBm
EIRP rounded down. The US limit is 30 dBm into an antenna of up to
6 dBi.

**The limit on transmitting counts frames by when they begin**, and
over any period, not hours by the clock. That is the reading no
regulator could find too generous, and a frame is at most 0.41 s long
at either profile.

**One coding rate.** The explicit header tells a receiver the coding
rate, so a later draft can let a sender choose a stronger one for a
weak link without changing this section's receivers.

## Not yet measured

These would be measured on a bench before this section is frozen. Until
then the values above stand on the published sources.

* **That `0x5E` is not received as `0x2B` or `0x12`, or they as it**, on
  the SX1262, SX1276 and LR1110, at each profile's settings.
* **That `0x5E` costs no sensitivity** against the radio's default sync
  words.
* **The 6 dB bandwidth of LoRa at 500 kHz** from the radios Tern runs
  on, against 15.247(a)(2)'s 500 kHz.
* **Power spectral density at full power**, against 15.247(e)'s 8 dBm in
  any 3 kHz. Spread evenly over 500 kHz, 30 dBm is 7.8 dBm in 3 kHz, so
  there is little to spare at the limit, and 8 dB at the SX1262's
  22 dBm. Australia's limit is on *peak* density, 25 mW (14 dBm) in any
  3 kHz; a chirp sweeps its band rather than filling it at once, so how
  far its peak stands above its average, at 500 kHz and SF9, is to be
  measured.

## Not yet specified

* **Other regions.** Each needs a profile, and some need rules of kinds
  this draft has no field for:
  * **India.** The 2021 rules for 865–868 MHz (G.S.R. 853(E), Table II)
    allow 500 mW ERP in at most 200 kHz, with adaptive power control,
    and a limit on transmitting that depends on the node: 10% for a
    network access point and 2.5% otherwise. A profile would need a
    limit for each role, and the routing design has not been simulated
    at 2.5%.
  * **Brazil.** 915–928 MHz is used there as in Australia, and
    LoRaWAN's AU915 plan with it; Anatel's conditions (Ato 14.448 of
    2017) are to be read before `AU915`'s channel is named for it.
  * **Japan and Korea** (listen before talk, and at most 4 s a
    transmission), **China** (470–510 MHz), the **AS923** countries and
    **433 MHz** (EU433, 10 mW ERP) need boards for other bands, listen
    before talk, a dwell limit, or more power than the band allows.
* **Links on other settings.** A scheduled MAC can put a link on a
  faster or slower spreading factor than the profile's. The range it
  may choose from belongs with the MAC.
* **More than one channel**, and hopping. In the US, hopping over 50
  channels of 125 kHz is the other lawful way to use the band.
* **Listen before talk.**
* **The airtime budget.**
