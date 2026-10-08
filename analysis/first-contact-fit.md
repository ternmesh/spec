# Does first contact fit one frame?

**Status:** analysis, not specification; nothing here is normative. It informed
[first contact](../draft/first-contact.md), which chose the `dh-first` case below: static DH
(method 3), the responder named by `kid` and the initiator sending its address.

The intent for first contact is EDHOC (RFC 9528) with cipher suite 0, with the session secret `S`
taken from its exporter ([unicast-security.md](../draft/unicast-security.md#not-yet-specified)).
The open question was whether each EDHOC message fits one frame at each region's slowest legal
setting. This answers it from public sources only: the message formats in RFC 9528, the LoRa
time-on-air formula Semtech publishes, and each region's rules as the LoRa Alliance's Regional
Parameters (RP002-1.0.4) and the rules themselves state them. No measurements are needed.

The numbers come from [`first_contact_fit.py`](first_contact_fit.py), which CI runs. It builds
each message to RFC 9528's structure byte for byte. Before anything else it checks that the
messages it builds for RFC 9529's two example traces have the lengths RFC 9529 publishes, and that
its time on air matches the reference table the simulator and the firmware test against, to the
nanosecond. As a further check against an independent source, the longest frames it finds under a
dwell limit, with LoRaWAN's 8-symbol preamble, are exactly the PHY payloads RP002 allows: 24 bytes
at US915 DR0 (400 ms), and 36, 99 and 197 bytes at CN470 DR1 to DR3 (1 s).

## Findings

1. **Every message fits one LoRa frame**, in every case below. The largest is 162 bytes, against
   255. EDHOC needs no fragmentation in Tern.
2. **Where there is no dwell limit, every message fits at the slowest setting** (EU868, EU433,
   RU864, IN865, and the US on 500 kHz channels). There the cost is airtime, not fit. In the EU's 1% sub-band at
   SF12, one handshake takes 13 to 23% of each side's hourly allowance, and the same in RU864.
   That is affordable once, but it is a reason to run first contact faster than SF12, or in a 10%
   band (EU868 at 869.4-869.65 MHz, or EU433), where it costs 1 to 2%.
3. **Under a 400 ms dwell limit, nothing fits at the slowest legal setting.** That setting is
   SF10/125 kHz (US915 hopping channels, and AS923 and AU915 where dwell applies), and it carries
   a frame of at most 19 bytes with a 16-symbol preamble, or 24 with 8. Even `message_4`, 24
   bytes in its frame, fits only with the shorter preamble, and `message_1`, 56 bytes, does not
   fit. First contact fits at SF8 for real first contact, and for nodes that already know each
   other's keys too unless the preamble is 8 symbols, when SF9 will do; and at SF7 with
   signatures, or SF8 if only the initiator sends its key and the preamble is 8 symbols.
4. **This is a region-profile problem more than an EDHOC one.** A secured unicast frame carries
   23 bytes of overhead, so at SF10/125 kHz under 400 ms even an empty one does not fit. Tern's
   profile for dwell-limited regions will have to use SF9 or faster at 125 kHz, or the US 500 kHz
   channels, whatever first contact does. SF9 is not enough for first contact, though: under
   400 ms its longest frame is 57 bytes (16-symbol preamble), and first contact's `message_3` is
   80. SF8 carries 130 bytes, enough for the static Diffie-Hellman cases and not for
   signatures, and SF7 carries 250.
5. **Static Diffie-Hellman keys (EDHOC method 3) are much smaller than signatures (method 0).**
   For first contact the frames are 56, 60 and 80 bytes against 56, 117 and 137, which saves
   about 3.9 s of airtime per handshake at SF12/125 kHz (9.3 s against 13.3 s, both sides
   together, without `message_4`). Method 3 needs X25519 identity keys,
   so this turns on what a Tern address is, which is not yet decided. If addresses must also sign
   (broadcasts and announces, for instance), there is a cost either way: signature-based first
   contact, or one key used for both signing and key agreement, which needs a cryptographer's
   review.
6. **KR920 allows up to 4 s per frame.** First contact with static DH (`dh-kid` and `dh-first`)
   fits at SF12. `dh-value` and the signature cases need SF11.
7. **CN470 allows up to 1 s per frame**, too little for anything at SF12 (RP002 calls that rate
   N/A). First contact with static DH (`dh-kid` and `dh-first`) fits at SF10; `dh-value` and
   the signature cases need SF9.

CN779 is left out: RP002 deprecates it, and no new devices may be installed there.

## Assumptions

* **The frame.** As [first contact](../draft/first-contact.md#the-frame) has it: the 11-byte
  head every [frame that follows a route](../draft/forwarding.md#the-head) starts with, a 4-byte
  tag the two ends match on, and no Tern AEAD tag, because EDHOC protects its own messages. That
  is 15 bytes, and `message_1`'s frame carries the initiator's 4-byte routing id as well. The
  frame type tells a receiver that a frame is `message_1`, so it is not prefixed with `true`
  (RFC 9528, 3.4.1). An earlier draft's frame had 8 bytes before the message and was heard only
  by the node it was for; the figures here were 7 and 11 bytes smaller then.
* **Credentials.** By reference, a one-byte `kid`, as in RFC 9529's second trace. By value, a
  `kccs` header (RFC 9528, 10.6) holding a CWT Claims Set with just the raw public key, with no
  subject or other claims, because a Tern address is the key. That is 46 bytes.
* **Connection identifiers** are one byte each, sent as integers.
* **No external authorization data** (EAD), so no padding. Anything Tern adds in EAD, or any
  padding to hide which case is in use, comes out of the headroom.
* **Radio:** CR 4/5, explicit header, CRC on, low data rate optimisation where a symbol lasts
  16 ms or more. The preamble is 16 symbols, as in the unicast draft's example, unless a table says
  otherwise.
* **Regions:** each region's slowest setting is the slowest LoRaWAN data rate RP002 gives it. Tern
  is not LoRaWAN, but that is the slowest setting devices in each region are commonly certified
  and deployed at. Tern's own region profiles are not decided. This is not legal advice.

The cases are:

* `dh-kid`: static DH, and each side names the other's key by `kid`. Two nodes that have met
  before.
* `dh-first`: static DH, first contact. The initiator knows the responder's address, which is its
  key, so the responder names its key by `kid`. The responder does not know the initiator, so the
  initiator sends its key.
* `dh-value`: static DH, and both sides send their keys.
* `sig-first` and `sig-value`: as `dh-first` and `dh-value`, with Ed25519 signatures (method 0).

`message_4` is optional in EDHOC. It is required only when the responder sends no protected
message of its own afterwards (RFC 9528, 5.5). In Tern, the responder's first secured unicast frame
could confirm the key instead, saving a frame. That is for the first-contact section to decide, so
the tables count it separately where it matters.

## Results

<!-- generated by first_contact_fit.py: begin -->

### Message sizes

Bytes of each EDHOC message, and in brackets the frame that carries it, with the 15-byte prefix. `message_4` is optional (see below).

| Case | `message_1` | `message_2` | `message_3` | `message_4` |
|---|---|---|---|---|
| `dh-kid`: Static DH, both known: each names the other's key by `kid` | 37 (56) | 45 (60) | 19 (34) | 9 (24) |
| `dh-first`: Static DH, first contact: the initiator knows the responder's address and sends its own key | 37 (56) | 45 (60) | 65 (80) | 9 (24) |
| `dh-value`: Static DH, both send their keys | 37 (56) | 90 (105) | 65 (80) | 9 (24) |
| `sig-first`: Signatures, first contact: as `dh-first`, with Ed25519 signatures | 37 (56) | 102 (117) | 122 (137) | 9 (24) |
| `sig-value`: Signatures, both send their keys | 37 (56) | 147 (162) | 122 (137) | 9 (24) |

### Regions with a dwell limit

The longest frame each region's slowest setting can carry, and the slowest spreading factor at which every frame of the handshake fits, `message_4` included. CR 4/5, explicit header, CRC on. Preamble 16 symbols, and 8 after the slash.

| Region | Slowest | Longest frame | `dh-kid` | `dh-first` | `dh-value` | `sig-first` | `sig-value` |
|---|---|---|---|---|---|---|---|
| US915, 125 kHz, hopping | SF10/125 | 19 B / 24 B | SF8 / SF9 | SF8 / SF8 | SF8 / SF8 | SF7 / SF8 | SF7 / SF7 |
| AS923 and AU915, where dwell applies | SF10/125 | 19 B / 24 B | SF8 / SF9 | SF8 / SF8 | SF8 / SF8 | SF7 / SF8 | SF7 / SF7 |
| KR920 | SF12/125 | 90 B / 100 B | SF12 / SF12 | SF12 / SF12 | SF11 / SF11 | SF11 / SF11 | SF11 / SF11 |
| CN470 | SF12/125 | 0 B / 10 B | SF10 / SF10 | SF10 / SF10 | SF9 / SF9 | SF9 / SF9 | SF9 / SF9 |

### Regions without one

Every frame fits at the slowest setting, so what matters is time on air: milliseconds each side transmits for the handshake (initiator: messages 1 and 3; responder: message 2, and 4 if sent), at a 16-symbol preamble. Where there is a duty cycle, the share of one hour's allowance that is.

| Region | Slowest | Case | Initiator, ms | Responder, ms (+ `message_4`) | Share of the hour |
|---|---|---|---|---|---|
| EU868, 868.0-868.6 MHz | SF12/125 | `dh-kid` | 4,964 | 2,892 (+1,745) | 13.8% / 12.9% |
| EU868, 868.0-868.6 MHz | SF12/125 | `dh-first` | 6,439 | 2,892 (+1,745) | 17.9% / 12.9% |
| EU868, 868.0-868.6 MHz | SF12/125 | `dh-value` | 6,439 | 4,366 (+1,745) | 17.9% / 17.0% |
| EU868, 868.0-868.6 MHz | SF12/125 | `sig-first` | 8,405 | 4,858 (+1,745) | 23.3% / 18.3% |
| EU868, 868.0-868.6 MHz | SF12/125 | `sig-value` | 8,405 | 6,332 (+1,745) | 23.3% / 22.4% |
| EU868, 869.4-869.65 MHz | SF12/125 | `dh-kid` | 4,964 | 2,892 (+1,745) | 1.4% / 1.3% |
| EU868, 869.4-869.65 MHz | SF12/125 | `dh-first` | 6,439 | 2,892 (+1,745) | 1.8% / 1.3% |
| EU868, 869.4-869.65 MHz | SF12/125 | `dh-value` | 6,439 | 4,366 (+1,745) | 1.8% / 1.7% |
| EU868, 869.4-869.65 MHz | SF12/125 | `sig-first` | 8,405 | 4,858 (+1,745) | 2.3% / 1.8% |
| EU868, 869.4-869.65 MHz | SF12/125 | `sig-value` | 8,405 | 6,332 (+1,745) | 2.3% / 2.2% |
| US915, 500 kHz | SF12/500 | `dh-kid` | 1,118 | 641 (+395) | - |
| US915, 500 kHz | SF12/500 | `dh-first` | 1,446 | 641 (+395) | - |
| US915, 500 kHz | SF12/500 | `dh-value` | 1,446 | 969 (+395) | - |
| US915, 500 kHz | SF12/500 | `sig-first` | 1,815 | 1,051 (+395) | - |
| US915, 500 kHz | SF12/500 | `sig-value` | 1,815 | 1,337 (+395) | - |
| IN865 | SF12/125 | `dh-kid` | 4,964 | 2,892 (+1,745) | - |
| IN865 | SF12/125 | `dh-first` | 6,439 | 2,892 (+1,745) | - |
| IN865 | SF12/125 | `dh-value` | 6,439 | 4,366 (+1,745) | - |
| IN865 | SF12/125 | `sig-first` | 8,405 | 4,858 (+1,745) | - |
| IN865 | SF12/125 | `sig-value` | 8,405 | 6,332 (+1,745) | - |
| RU864 | SF12/125 | `dh-kid` | 4,964 | 2,892 (+1,745) | 13.8% / 12.9% |
| RU864 | SF12/125 | `dh-first` | 6,439 | 2,892 (+1,745) | 17.9% / 12.9% |
| RU864 | SF12/125 | `dh-value` | 6,439 | 4,366 (+1,745) | 17.9% / 17.0% |
| RU864 | SF12/125 | `sig-first` | 8,405 | 4,858 (+1,745) | 23.3% / 18.3% |
| RU864 | SF12/125 | `sig-value` | 8,405 | 6,332 (+1,745) | 23.3% / 22.4% |
| EU433 | SF12/125 | `dh-kid` | 4,964 | 2,892 (+1,745) | 1.4% / 1.3% |
| EU433 | SF12/125 | `dh-first` | 6,439 | 2,892 (+1,745) | 1.8% / 1.3% |
| EU433 | SF12/125 | `dh-value` | 6,439 | 4,366 (+1,745) | 1.8% / 1.7% |
| EU433 | SF12/125 | `sig-first` | 8,405 | 4,858 (+1,745) | 2.3% / 1.8% |
| EU433 | SF12/125 | `sig-value` | 8,405 | 6,332 (+1,745) | 2.3% / 2.2% |

### Sources for each region

* **EU868, 868.0-868.6 MHz:** RP002 2.4: under 1% on its default channels, no dwell limit; DR0 is SF12.
* **EU868, 869.4-869.65 MHz:** ERC Recommendation 70-03, Annex 1: 500 mW, under 10%; RP002 2.4: no dwell limit.
* **US915, 125 kHz, hopping:** 47 CFR 15.247(a)(1)(i): 0.4 s on any one channel; RP002 2.5: DR0 is SF10.
* **US915, 500 kHz:** 47 CFR 15.247(a)(2): digital modulation, no dwell limit; RP002 2.5: DR8 is SF12.
* **AS923 and AU915, where dwell applies:** RP002 2.8, 2.10: where UplinkDwellTime is 1 (400 ms), which is country by country, DR2, SF10, is the slowest.
* **KR920:** RP002 2.11.6: under 4 s per frame, with LBT.
* **IN865:** RP002 2.12: no dwell or duty cycle limit.
* **RU864:** RP002 2.13: under 1% on its default channels, no dwell limit.
* **EU433:** RP002 2.7: under 10%, no dwell limit.
* **CN470:** RP002 2.9.2: a transmission may not exceed one second, so at SF12 (DR0) LoRaWAN carries nothing.

<!-- generated by first_contact_fit.py: end -->

## What the first-contact section should decide

* **The setting first contact runs at, per region profile.** In dwell-limited regions it cannot be
  the slowest legal one, and it has to be SF8 or faster at 125 kHz, faster than the SF9 that
  ordinary unicast needs there (finding 4). It could also be the US 500 kHz channels.
* **Method 3 or method 0**, which follows from what a Tern address is (finding 5).
* **Whether `message_4` is sent,** or the responder's first unicast frame confirms the key.
* **The frame type for EDHOC messages**, and how its 4-byte field correlates them.

## Sources

* RFC 9528, *Ephemeral Diffie-Hellman Over COSE (EDHOC)*: message formats (section 5), compact
  `kid` encoding (3.5.3.2), message correlation (3.4.1), `kccs` (10.6).
* RFC 9529, *Traces of EDHOC*: message lengths for methods 0 and 3, which the tool reproduces.
* LoRa Alliance, *RP002-1.0.4 LoRaWAN Regional Parameters* (2022): per-region data rates, dwell
  time and duty cycle.
* 47 CFR 15.247: the US 902-928 MHz dwell limit for hopping systems, and digital modulation.
* ERC Recommendation 70-03, Annex 1: the EU's 869.4-869.65 MHz band.
* Semtech, SX1261/2 datasheet and AN1200.13: time on air, as implemented in
  `ternmesh/firmware` (`src/lora.c`) and `ternmesh/sim`.
