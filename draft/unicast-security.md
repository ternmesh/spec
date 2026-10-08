# Secured unicast frames

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It has not yet been
reviewed by a cryptographer, and it must be before it is frozen.

This section defines how one node sends a private message to another
once the two already share a session: the bytes on the air, the keys,
and what the receiver does. How two nodes come to share a session is
[first contact](first-contact.md).

Test vectors: [`vectors/unicast-security.json`](../vectors/unicast-security.json),
produced by [`vectors/tools/unicast.py`](../vectors/tools/unicast.py).

## Goals

1. **Little overhead.** Every byte is airtime, and airtime is the
   metered resource. The frame carries 23 bytes of overhead, against 28
   for a Meshtastic direct message: 13 of its own, and the 10 that
   [carry it along a route](forwarding.md#the-head). For a 40-byte text
   at SF11/250 kHz (CR 4/5, 16-symbol preamble) that is 723 ms on the
   air instead of 764 ms.
2. **Nothing of its own in clear that names either end.** What this
   section puts in a frame shows an observer no sender, no recipient
   and no message counter, only values that look random and change with
   every message. The routing layer's ten bytes do name the node the
   frame is for, by its routing id: see
   [What an observer learns](forwarding.md#what-an-observer-learns).
   They do not name the sender.
3. **No time sync needed.** A node can receive a unicast message without
   knowing the time.
4. **Forward secrecy, in steps.** A node that is captured later gives
   up at most the last 64 messages in each direction, provided it has
   erased keys as this section requires and its receive window is still
   advancing. A session whose receiver has stalled (see
   [Not yet specified](#not-yet-specified)) does not have this
   property.
5. **Standard primitives only.** HKDF-SHA-256 and AES-128, in modes
   with published test vectors, so any implementation can be checked
   against more than this document.

## Notation

* `||` is concatenation; `x[a..b]` is bytes `a` to `b - 1` of `x`.
* `u32be(n)` is `n` as four bytes, most significant first.
* `0^k` is `k` zero bytes.
* `Expand(K, info, L)` is HKDF-Expand from RFC 5869 with SHA-256, keyed
  with `K`, returning `L` bytes. Labels in quotes are ASCII, with no
  terminator.
* `AES(K, x)` is one AES-128 block encryption of the 16-byte `x`.
* `CCM(K, N, A, P)` is AES-128-CCM (RFC 3610) with an 8-byte tag
  (M = 8), a 2-byte length field (L = 2) and the 13-byte nonce `N`,
  authenticating `A` and encrypting `P`. Its output is the ciphertext
  followed by the tag, `len(P) + 8` bytes. This is the AEAD that COSE
  calls AES-CCM-16-64-128 (RFC 9053), the one EDHOC cipher suite 0
  uses.

## The session

A session is shared by two nodes, the **initiator** and the
**responder**, and is defined by a 32-byte **session secret** `S`. Each
session carries messages in two **directions**, numbered `d`:

| `d` | Messages sent by |
|---|---|
| `0x01` | the initiator |
| `0x02` | the responder |

Each direction has its own keys and its own **counter** `n`, a 32-bit
unsigned integer that starts at 0. Nothing in one direction depends on
the other.

## Keys

For direction `d`:

```
TK_d     = Expand(S, "tern v0 tag"   || d, 16)        tag key
IV_d     = Expand(S, "tern v0 iv"    || d, 13)        nonce base
EK_d(0)  = Expand(S, "tern v0 epoch" || d, 32)        first epoch key
EK_d(e+1) = Expand(EK_d(e), "tern v0 next", 32)       each next epoch key
```

Message `n` belongs to **epoch** `e = floor(n / 32)`, so an epoch is 32
messages. For message `n`:

```
MK_d(n)    = Expand(EK_d(e), "tern v0 msg" || u32be(n), 16)   message key
dtag_d(n)  = AES(TK_d, 0^12 || u32be(n))[0..4]                destination tag
N_d(n)     = IV_d XOR (0^9 || u32be(n))                       nonce
```

The epoch keys form a one-way chain: from `EK_d(e)` anyone can compute
every later epoch key, but not an earlier one. Deleting old epoch keys
is what gives forward secrecy, and only if `S` is deleted too, because
`S` regenerates the whole chain:

* A node MUST erase `S` once it has derived `TK_d`, `IV_d` and
  `EK_d(0)` for both directions. `TK_d` and `IV_d` are kept for the
  life of the session; neither yields a message key.
* `EK_d(e)` is the only way to reach `EK_d(e+1)` once `S` is gone. So
  before a node erases `EK_d(e)` under the rules below, it MUST derive
  `EK_d(e+1)` and keep it, unless `e` is the last epoch, `2^27 - 1`
  (counters `2^32 - 32` to `2^32 - 1`).

## The frame

| Offset | Bytes | Field | Authenticated |
|---|---|---|---|
| 0 | 1 | `hdr`: format, type and flags | yes |
| 1 | 10 | `route`: for the routing layer | no |
| 11 | 4 | `dtag`: the destination tag | yes |
| 15 | `p` | ciphertext | yes (encrypted) |
| 15 + `p` | 8 | AEAD tag | |

The frame is `23 + p` bytes. A LoRa frame carries at most 255 bytes, so
`p` is at most 232.

`hdr` is laid out as:

| Bits | Field | Value in this section |
|---|---|---|
| 7–6 | format | `01`: draft 0 |
| 5–3 | type | `001`: secured unicast |
| 2–0 | flags | `000`: none defined |

So `hdr` is `0x48`. Other formats, types and flags are reserved.

`route` belongs to the routing layer, which defines it in
[Frames that follow routes](forwarding.md#the-head): `hops`, `power`,
`next` and `destination`. With `hdr` before it, it is the head every
frame that follows a route starts with, and `dtag` is what that section
calls the frame's `tag`. Relays change part of `route` on every hop, so
none of it is authenticated end to end: a frame whose `destination` has
been changed goes astray, as one that is dropped does, and the node it
reaches holds no tag for it.

As first drafted, this frame held three bytes for the routing layer,
`hop` and `label`, with the destination tag at offset 4 and 16 bytes of
overhead. No frame of that layout is a frame of this section.

## Sending

To send plaintext `P` as message `n` in direction `d`:

1. A sender MUST use `n` = 0 for its first message in a direction, and
   MUST add exactly one for each message after. Skipping a counter
   would take the receiver's window past it (see
   [Receiving](#receiving)), and resynchronising is not yet specified.
   So a sender never sends two frames with the same `S`, `d` and `n`.
2. A sender MUST NOT send with `n` above `2^32 - 1`. A sender that has
   used every counter needs a new session.
3. The sender computes `dtag_d(n)`, and sets
   `A = hdr || dtag_d(n)`.
4. The frame is
   `hdr || route || dtag_d(n) || CCM(MK_d(n), N_d(n), A, P)`, with
   `route` as the routing layer sets it.
5. Once a sender has sent every message it will send in epoch `e`, it
   MUST derive and keep `EK_d(e+1)` (unless `e` is the last epoch), and
   then MUST erase `EK_d(e)` and every message key derived from it.

## Receiving

A receiver holds, for each session and for the direction it receives
in, the highest counter it has accepted, `H` (none to begin with). Its
**window** is every counter from `max(0, H - 31)` to
`min(H + 32, 2^32 - 1)` (from 0 to 31 before anything is accepted),
leaving out counters it has already accepted. A window never holds a
counter outside 0 to `2^32 - 1`, so nothing wraps.

For each counter in its window, the receiver keeps `dtag_d(n)` in a
table that maps a tag back to its session, direction and counter. The
tags of every session it holds go in the same table, so a frame is
matched with one lookup however many contacts the node has.

To receive a frame:

1. A receiver MUST discard a frame shorter than 23 bytes, or whose
   `hdr` is not one it implements.
2. It looks up bytes 11 to 14 in its table. If there is no match, the
   frame is not for this node, and the receiver MUST NOT treat it as an
   error.
3. For each match, in any order, it computes `A = hdr || dtag`, and
   checks and decrypts the ciphertext with `MK_d(n)` and `N_d(n)`. Four
   bytes can match more than one entry, so a receiver MUST try every
   match before deciding that a frame fails.
4. A receiver MUST NOT accept a frame unless the AEAD check passes, and
   MUST NOT accept the same `S`, `d` and `n` twice.
5. On accepting message `n`, the receiver removes `n` from its window.
   If `n > H`, it sets `H = n`, adds the counters that have entered the
   window, and drops those that have left it.
6. Once every counter in epoch `e` has left its window, a receiver
   MUST derive and keep `EK_d(e+1)` if it does not already hold it
   (unless `e` is the last epoch), and then MUST erase `EK_d(e)` and
   every message key derived from it.

`route` plays no part in the check: a frame is accepted whatever it
holds. Whether a frame is this node's to open at all is the routing
layer's to say, from `destination`, before any of this.

A frame that is not accepted may still be a copy of one that was, sent
again because its acknowledgement was lost.
[Frames that follow routes](forwarding.md#messages) says which copies a
receiver answers, and with what.

## Conformance

An implementation conforms to this section if, for every case in
[`vectors/unicast-security.json`](../vectors/unicast-security.json):

* **accepted:** given `session_secret`, `direction`, `counter`, `hops`,
  `power`, `next`, `destination` and `plaintext` (setting the counter is
  a test hook; in use, a sender chooses it, as `senders` checks), it
  produces exactly `frame`, and, as a
  receiver holding `session_secret` and expecting `counter`, it accepts
  `frame` and recovers `plaintext`;
* **rejected:** as a receiver holding `session_secret` and expecting
  `counter` in `direction`, it rejects `frame`;
* **sequences:** as a receiver of a new session holding
  `session_secret`, receiving in `direction`, given each frame of
  `deliveries` in order, it accepts exactly those whose `accept` is
  true, with that `counter` and `plaintext`, and rejects the rest.
  These check the window and that a replay is rejected, which a single
  frame cannot;
* **collisions:** as a receiver holding every session in `sessions`,
  all new, with their tags in one table, given each frame of
  `deliveries` in order, it accepts exactly those whose `accept` is
  true, attributed to the session and counter given. The two sessions' tags collide, so this
  checks that every matching entry is tried, and, where both frames go
  to one receiver, that accepting one removes only its own entry;
* **senders:** as both ends of a new session holding `session_secret`,
  given each send of `sends` in order (`direction` and `plaintext`, with
  `route` as the file's description gives it), choosing every counter
  itself, it produces
  exactly that send's `frame`. These check that a sender starts at 0,
  adds one each time and never repeats a counter, and that the two
  directions count separately, which a case that is handed its counter
  cannot.

The erasure requirements (in [Keys](#keys), step 5 of Sending and step
6 of Receiving) cannot be checked from outside a node, by vectors or
otherwise. They are requirements nonetheless, because without them the
forward secrecy this section claims does not exist; they are checked by
reviewing an implementation, not by the suite.

Each case also gives the intermediate values (epoch key, message key,
tag key, nonce base, nonce, tag and the acknowledgement's `proof`) to
help find where an implementation goes wrong.

The file's `acknowledgements`, and `acknowledge` and `proof` in its
`sequences` and `collisions`, are for
[Frames that follow routes](forwarding.md#conformance), which defines
what they check. They are in this file because they need its keys.

## Rationale

**AES-128-CCM with an 8-byte tag.** It is the AEAD of EDHOC cipher
suite 0, which [first contact](first-contact.md) uses, so a node
needs one cipher, not two. It is also what IEEE 802.15.4 and Bluetooth
LE use, so many radio microcontrollers have it in hardware; the
nRF52840 does. ChaCha20-Poly1305 was considered: it is faster in
software and harder to get wrong without hardware, but its standard
form has a 16-byte tag, and truncating it is not a standard
construction. Implementations on chips without AES hardware should use
a constant-time software AES.

**Eight bytes of tag, not sixteen.** Each forgery attempt costs the
attacker a transmission on a channel where airtime is limited by
regulation. At one attempt per second, 2^64 attempts take about 585
billion years. LoRaWAN uses a 4-byte tag for the same reason. Saving 8
bytes per frame matters more here.

**A blinded tag instead of addresses.** Meshtastic sends sender,
recipient and packet id in clear. Here what tells a receiver that a
frame is one it can open is four bytes that only the two ends of the
session can compute, and that change with every message. The receiver
works out the sender and the counter from which tag matched, so neither
travels. The recipient's routing id does travel, in `route`, for the
nodes that pass the frame along.

**Tags from the counter, not from time.** The tag depends only on the
counter, so a receiver needs no clock to know which tags to expect.
Bluetooth's resolvable private addresses likewise need no clock to
resolve.

**Four bytes of tag.** A random frame matches one of `T` table entries
with probability about `T / 2^32`. With 100 contacts and a 64-counter
window (6,400 entries), that is about one false match in 670,000 frames,
and a false match costs only one failed AEAD check.

**A key per message, from a chain of epoch keys.** A fresh message key
for each counter means a nonce can never repeat under one key, however
an implementation handles counters. The epoch chain gives forward
secrecy without a full Double Ratchet, whose store of skipped keys can
reach about 80 KB per session. Here a receiver keeps at most three epoch
keys per session: the window spans 64 counters, so it touches at most
three epochs.

**Window of 64.** Thirty-one behind tolerates reordering and loss on a
multi-hop path. Thirty-two ahead means that after the last accepted
message, up to 31 can be lost in a row: if 32 are, the next to arrive is
`H + 33`, outside the window, and the session needs resynchronising.

## Not yet specified

Each of these is needed before the specification is frozen, and is
deliberately left out of this draft:

* **A Diffie-Hellman step.** The epoch chain heals nothing: a node whose
  current epoch key is stolen loses every later message in that
  direction. A periodic DH step (MSH-36) would fix that, at the cost of
  public keys on the air.
* **Resynchronising** a session after 32 or more lost messages in a
  row. Until then, a receiver that has lost that many has stalled: no
  later frame is in its window, so it never advances, and it keeps an
  epoch key from which every later epoch key can be derived. Capturing
  it exposes every message its peer sends afterwards, not only the last
  64. The fix belongs with resynchronisation: an expiry that erases a
  stalled chain, or a way to move the window forward safely.
* **Length.** The ciphertext is as long as the plaintext, so an
  observer learns the message's length. Padding costs airtime, and the
  trade-off is undecided.
* **Groups, broadcast and announces**, each a different frame type.
* **Measured cost on the nRF52840:** tag lookups at 50, 100 and 500
  contacts, AES and HKDF timings, and RAM per session.
