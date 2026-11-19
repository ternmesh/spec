# Who is talking to whom: what goes over the air, and what could stop it

**Status:** proposal and analysis, not specification. Nothing here is normative. It is written for
the maintainer to decide on, under [GOVERNANCE.md](../GOVERNANCE.md#who-decides). If it is
accepted, the changes it lists go to the drafts as their own pull requests. The simulator results
are from `ternmesh/sim` on the branch `claude/privacy-design` (`tools/rotate.py`, and `rotate_s` in
`include/tsim/core.h`), run on the firmware's own routing code. Part 1 has since been adopted
([routing.md](../draft/routing.md#rationale), "A blinded key, not the address"). Requirement 1 of
Part 2 was measured afterwards: see [Freeing places network-wide,
measured](#freeing-places-network-wide-measured).

## Summary

The website says: *"Private by default: what goes over the air is meant to reveal as little as
possible about who is talking to whom."* Today the drafts do not deliver that.

* Every node puts its long-term address in clear in its announces, so that neighbours can check
  their signatures.
* Every routed frame names its destination and next hop by routing ids that never change.
* So a listener anywhere in the mesh can map routing ids to addresses, see which node each frame
  is for, see the topology, and follow a node for as long as it runs.
* The payloads themselves are well hidden: unicast frames carry blinded, counter-derived tags and
  groups carry random-nonce tags.

This document proposes two steps and measures the second:

1. **Announces signed with a blinded key, not the address.** A node signs its announces with a key
   blinded from its identity key, as Tor's v3 onion services blind theirs. Its routing id is made
   from that key.
   * Anyone who knows the address can still compute the routing id and route to the node.
   * No one else can recover the address from what is on the air.
   * Only the holder of the identity key can speak for the id, which is the property signing was
     added for.
   * It costs **no airtime and no routing churn**. The blinded key takes the address's 32 bytes,
     and the id is as stable as today's.
   * **Recommended now.**
2. **Routing ids that change every epoch,** derived as above with the epoch in the blinding. This
   cuts the link between one epoch's traffic and the next for anyone who does not know the address.
   Measured on the firmware's routing code, 1000 nodes, EU868's and US915's settings:
   * With the boards' 1024 destination places, rotating every id at once left unicast delivery at
     3 to 10% for at least five hours, against 96 to 98%. The old names and the new need a place
     each, and there are not enough.
   * With room for both (2048 places is enough) it recovers within 11 to 15 hours. Averaged over
     an epoch, a **daily** rotation costs 11 to 13 points of unicast and 9 to 15% more airtime. A
     **weekly** one costs about 2 points and 1 to 2%.
   * Measured afterwards: if every node marks its places old at the epoch's start, a new name may
     take an old place, and five minutes in each node forgets the neighbours it has not heard
     since. Then the board's 1024 places are enough, nothing more goes on the air, and a **weekly**
     rotation costs 1.3 to 1.4 points of unicast on EU868's and US915's settings, and 1.3 to 5.4
     with a fifth of the retirements lost. The slow preset pays about 15.
   * **Recommended: specify it, and leave it off,** with a weekly epoch, every node at once, off on
     the slow preset, and never on a node without a clock it trusts. Turn it on once the routing it
     depends on has been measured on radios.

The other leaks are covered in [Part 3](#part-3-the-other-leaks): acknowledgements,
`message_1`'s `source`, a flood's `hops`, frame kind and size. Some are fixed cheaply; the rest
are fundamental to a routed radio mesh and are stated as limits.

**What Tern could then honestly claim, in one sentence:**

> Messages are end-to-end encrypted and your address never goes on the air unless you turn on
> presence cards, but a listener can see which pseudonymous nodes exchange messages, and one nearby
> can tell when your radio sends.

With step 2 on, "pseudonymous nodes" becomes "pseudonyms that change every week", which cannot be
followed from one week to the next by anyone who does not already know the address.

## What leaks today

Each frame, and what a listener who hears it learns:

| Frame | Field in clear | What it gives away |
|---|---|---|
| Announce ([routing.md](../draft/routing.md#announces)) | `sender` | The node's routing id, fixed for life |
| | `address` (on starting, `ADDRESS_AFTER` after each neighbour found, and at least 1 in `ADDRESS_EVERY`) | **The long-term address**, and with it the map from routing id to address (routing.md: "anyone near can learn the address from the id") |
| | neighbours (`id`, `margin`) | Who hears whom, and how well: local topology |
| | routes (`destination`, `seq`, `metric`, leaf bit) | Which destinations a relay reaches, how far away, and which are leaves |
| | `flags` relay bit, `power`, `promise`, `round` | Role, transmit power, how often it announces |
| | `number`, `seq` | Counters that continue for ever, linking announces across any change of id |
| Request | `next`, each `destination` | That some node near wants a route to that destination |
| Solicit / answer | `sender`, `after`, `leaf` | A leaf's id, the relay it was attached to, and the relay it attaches to now: movement |
| Routed frame ([forwarding.md](../draft/forwarding.md#the-head)) | `next`, `destination` | Who the frame is for, and who carries it next |
| | `hops` = `HOP_MAX` | The transmitter is the source. A leaf never relays, so *any* routed frame a leaf sends is its own |
| | `hdr` `0x48`/`0x49` | Whether a message is words, or a position or invite for the node |
| | length | The message's length, to the byte |
| Acknowledgement | `destination`, `tag` (= the message's destination tag) | **The source of the message.** Hearing both frames gives both ends |
| First contact `message_1` | `destination`, `source` | **Both ends** in one frame |
| Flood ([flooding.md](../draft/flooding.md#what-an-observer-learns)) | `hops` = `FLOOD_HOPS` | The transmitter wrote it. Its group is hidden: the tags are random |
| Card ([cards.md](../draft/cards.md)) | `address`, name | Everything; off by default and opt-in, as intended |

Claims in the drafts that this contradicts, and that should be corrected **whatever is decided**:

* [cards.md](../draft/cards.md#goals): "A card puts its sender's address in clear. Every other
  frame keeps it out". Announces carry it too.
* [cards.md](../draft/cards.md#goals) goal 2: a node without cards "is as private as it was". True,
  but it was not private: its announces carry its address.
* [cards.md](../draft/cards.md#what-an-observer-learns): what a card does not tell is "who the node
  talks to". Routed frames and acknowledgements do, by routing id, to anyone who maps ids to
  addresses from announces.
* [companion.md](../draft/companion.md#rationale), "Why nothing derived from the address in
  advertisements": "The radio protocol keeps a node's address out of the clear." It does not.
* [first-contact.md](../draft/first-contact.md#goals) goal 2, "No address in clear", holds for the
  handshake's own frames. But the responder's address is in its announces, and so is the
  initiator's.

routing.md's own [What an observer learns](../draft/routing.md#what-an-observer-learns) and
forwarding.md's are accurate. The contradictions are in the sections that refer to them.

## Who is listening

The analysis below distinguishes four observers:

* **(a) A listener far from you:** in range of some relays your traffic crosses, not of you. One
  receiver, or a network of them across a town.
* **(b) A listener near you:** hears every frame your radio sends, and your neighbours'.
* **(c) A relay:** a participant. Anyone may run one, and any relay on your path carries your
  frames, or hears your announces. It holds what a node holds: routes, neighbours' keys.
* **(d) Someone who knows your address:** a contact, anyone you showed a QR code or link to
  ([sharing.md](../draft/sharing.md)), and anyone who heard your card.

## Limits no design here removes

These hold for any routed LoRa mesh with Tern's budget. They should be stated, not designed
around.

1. **Relays must know a name for every destination.** A frame goes hop by hop only if each relay
   has a route to *something* the frame names, and in a distance-vector mesh every relay holds a
   route to every destination it can reach. So any participant, (c), learns the set of names and
   roughly where each is. Hiding the destination from the relays carrying it takes onion or mix
   routing: a layer of keyed header per hop, and paths chosen by the source. That costs tens of
   bytes per hop, and sources would need to know the topology (Danezis and Goldberg's Sphinx
   format is the compact reference, at 32 or more bytes per hop). At 1.1 to 8 ms of airtime a byte
   on Tern's profiles, that is out of reach.
2. **A radio is its own identifier to someone near it.** Received signal strength, timing, and the
   transmitter's own imperfections (frequency offset; Brik et al., "Wireless device identification
   with radiometric signatures", MobiCom 2008) let observer (b) follow a transmitter whatever ids
   it uses. Changing ids defeats an observer who sees only some of a node's frames, or sees them on
   different days, or far apart. It does not defeat one sitting next to the node.
3. **A reply must find its way back.** An acknowledgement, or `message_2` of first contact, has to
   be routed to the node that sent the message, so the sender's routable name is on the air in the
   reply. The ways round this (return paths held at relays, reply blocks) were considered and set
   aside in [first-contact.md](../draft/first-contact.md#rationale), and they protect little while
   the first acknowledgement gives the same.
4. **Timing.** With no cover traffic, a frame leaving one place and one arriving at another a
   moment later can be correlated by observer (a) with receivers at both. Cover traffic costs
   airtime that the [budget](../draft/airtime.md) does not have.
5. **Whoever knows your address can find your routing id.** They have to, to route to you; that is
   observer (d) under every design here.

## Part 1: announces without the address

### Why the address is there

[routing.md](../draft/routing.md#signed) signs announces so that only the holder of an address can
speak as the routing id made from it. That rules out forged announces that would draw frames, make
a neighbour look like it is starting, or invent margins. A signature is checked against a public
key, Tern's public key *is* the address, so the address goes on the air. routing.md's rationale
rejected a separate routing key: "nothing would tie that key to the routing id, and a node could
then claim the id of any destination its neighbours had not heard from".

### Options

| | Option | Sybil / hijack property | Address on air | Cost | Verdict |
|---|---|---|---|---|---|
| A1 | Today: sign with the address, carry it | Only the address holder speaks as `rid(A)` | Yes | 32 bytes on some announces | The problem |
| A2 | Send the address only encrypted, to neighbours who already know the node | As today, for those neighbours | No, to those | A new neighbour cannot check the first announce it hears: it needs the address to decrypt, and has none. Needs a per-neighbour handshake first | Rejected: a chicken-and-egg problem, plus a handshake per link |
| A3 | Per-neighbour pairwise keys, a MAC per neighbour instead of a signature | Pairwise only | No | 8 bytes per neighbour named: as much as a signature at 8 neighbours, more beyond | Rejected, as routing.md already rejected it |
| A4 | A key shared by each node with its neighbours (one MAC per announce, the key handed to each neighbour pairwise) | **Lost.** Every neighbour holding the key can forge the node's announces to the others. A symmetric MAC cannot authenticate a broadcast source without delayed disclosure (TESLA; Perrig et al., IEEE S&P 2000), which routing.md measured and set aside | No | 16 bytes instead of 64, after a handshake per link | Rejected: gives up what signing was added for |
| A5 | A random routing key per node, `rid = rid(key)`, unrelated to the address | The key is tied to the id, so only the key holder speaks as it | No | None on the air. But a node that knows only an address cannot find the id: first contact, and every contact, would need the id handed over off the air or in session | Rejected: breaks "first contact to an address" |
| A6 | Accept that relays are public and only leaves private | As A1 for relays | Relays' yes | As A1 | Covered by Part 2's "leaves" variant |
| **A7** | **A key blinded from the identity key; `rid` made from it** | **As A1:** only the identity key's holder can make signatures under the blinded key, and the id is tied to the blinded key | **No.** Only someone who already knows `A` can compute the blinded key from it, or tell that a blinded key is `A`'s | **None**: 32 bytes where the address was. One scalar multiplication per contact, once | **Proposed** |

### The blinded key (A7)

The construction is Tor's for v3 onion services (rend-spec-v3, appendix A.2, "Key blinding"). Its
security for Ed25519 is argued in Hopper, "Proving security of Tor's hidden service identity
blinding protocol" (2013). The IRTF CFRG draft "Key Blinding for Signature Schemes"
(draft-irtf-cfrg-signature-key-blinding) generalises it. Written for Tern, with `e` an epoch number
(Part 2), and `e` = 0 for as long as ids do not change:

```
h_e   = SHA-512("tern v0 blind" || A || u32be(e))  reduced mod L        a 255-bit scalar
B_e   = [h_e] A                                                          the blinded key, 32 bytes
b_e   = h_e * a  mod L                   a the identity's secret scalar (Ed25519's, from sk)
p_e   = SHA-512("tern v0 blind prefix" || prefix || u32be(e))[0..32]    prefix as Ed25519 makes it
rid_e = rid(B_e)                                                         as routing ids are made now
```

An announce carries `B_e` where it carries the address now, and is signed with the secret scalar
`b_e` and nonce prefix `p_e`. It is verified as Ed25519 against `B_e`, as now, so no verifier
changes. `B_e` is in the prime-order subgroup because `A` is, so the existing validity check is
unchanged.

What each party can do:

* **The node** derives `b_e` and `p_e` from its seed: no new secret to store.
* **Anyone who knows `A`**: a contact, the initiator of first contact, someone who scanned your QR
  code. They compute `B_e` and `rid_e`: one variable-base scalar multiplication. They can check
  that the announces for `rid_e` are yours, and route to you exactly as today.
* **A listener who does not know `A`** sees `B_e`. Finding `A` from it, or linking `B_e` to
  `B_e'`, is as hard as the decisional Diffie-Hellman problem in the group (the Tor analysis
  above).
* **Hijack.** As today, only the holder of `a` can sign as `B_e`. Taking `rid_e` by grinding keys
  takes about 2^32 tries, as routing.md says for today's ids. Announcing false *routes* to it needs
  no grinding, as today.

What changes in the drafts:

* [routing.md](../draft/routing.md#announces): `address` becomes `key` (`B_e`); `rid` is made from
  `B_e`; "holds the address" becomes "holds the key". `ADDRESS_AFTER` and `ADDRESS_EVERY` keep
  their values and their names' meaning.
* [first-contact.md](../draft/first-contact.md#where-each-frame-goes): `rid(A_R)` becomes
  `rid_e(A_R)`. `message_1`'s `source` becomes the initiator's `rid_e`. EDHOC and its X25519 keys
  are unchanged: they use `A`.
* [cards.md](../draft/cards.md): unchanged. It says what turning cards on gives up, and should add
  that it lets anyone in earshot find your routing id.
* [sharing.md](../draft/sharing.md): say that sharing your address lets its holder recognise your
  routing id. That was true already.

**What it costs** (firmware at `76861e9`):

| | Cost |
|---|---|
| Airtime | **None.** 32 bytes where 32 were. The simulator does not distinguish the two |
| Routing | **None.** The id is as stable as today's while `e` = 0 |
| Flash | Under 1 KB, estimated. Variable-base scalar multiplication is in the firmware already (`tern_address_valid` computes `[L]A`), and so is reduction mod L (signing). New: hashing to `h_e`, multiplying two scalars mod L, and signing with a given scalar and prefix (a refactor of `tern_identity_sign`) |
| RAM | 64 bytes for the node's own `b_e` and `p_e`, derived at start or kept. 4 bytes per contact if each contact's `rid_e` is cached rather than recomputed. Neighbours already keep 32 bytes each for the address, now the key. On the classic ESP32, which has no static RAM to spare (`docs/releases/v0.5.0-alpha.3.md`), this comes from the heap, as the destination table already does |
| CPU | One scalar multiplication per contact, and for the node's own key, whenever `e` changes. A handshake costs several of these already ([first-contact.md](../draft/first-contact.md#not-yet-specified), measured cost pending) |
| Review | One more use of the identity key, besides Ed25519 and X25519. It adds to the review [first-contact.md](../draft/first-contact.md) already asks a cryptographer for |

## Part 2: routing ids that change

With Part 1 alone, `rid_0` is a stable pseudonym. Observer (a) cannot name it, but can follow it
for months, build a who-writes-to-whom graph between pseudonyms, and name a node later from one
side channel, such as where it sits each night. Ids that change bound all of that to an epoch.
Bluetooth's resolvable private addresses solve the same problem for advertisers. There the device
rotates on its own timer and a bonded peer resolves the address by trying its key; that works
because nothing has to route to the device. Tern's ids must be routable, so here they are derived
from the epoch instead, and anyone who holds the address computes the current one.

### How it would work

* **Epochs.** `e = floor(t / EPOCH)`, with `t` UTC seconds and an `EPOCH` such as seven days, so
  every node rotates at the same moment and the whole network changes names together. That is the
  largest anonymity set there can be (compare Bluetooth's resolvable private addresses, which each
  device rotates on its own timer).
* **Clock.** A node needs the epoch, not the time. Phones set it (`SET_TIME`) and GPS boards know
  it. A node with neither takes it from its neighbours: a one-byte `e mod 256` in every announce,
  taken from neighbours whose links are up when several agree. That costs a byte per announce. A
  wrong epoch makes a node unreachable to its contacts, so a node with a real clock ignores the
  byte. Senders try `e - 1`, `e` and `e + 1` and use whichever id they hold a route to, so a few
  minutes' skew costs nothing.
* **What a node keeps across a rotation:** everything. Its neighbours, routes and feasibility
  distances stay valid: they are per destination, and only the node's own id changes. That keeps
  loop-freedom as it is. Its `number` and `seq` are re-based on a per-epoch value derived from
  the seed, so they do not link the epochs. The "only rises" rule then applies within an epoch,
  across restarts, as today.
* **Retiring the old id.** At the boundary a node sends one announce under its old key, flagged
  *retired* and signed like any other. A neighbour that hears it forgets the sender and every route
  through it at once, as on `DEAD_HOPS`, and retracts what it announced through it. The new id's
  announces then go at once, carrying `B_e`, with Trickle reset.
* **Frames in flight.** A node accepts frames for `rid_{e-1}` for a few minutes after the
  boundary. Sources recompute the destination for every new message.

Neither the retirement nor the epoch byte is in the simulator's frames. The retirement is modelled
as heard by every neighbour (the best case). Without it, the old id stays in neighbours' tables
until `SILENT_MAX` (24 h) and two promises, which the "silent" rows below measure.

### What it costs: the destination table

In a distance-vector mesh every relay keeps a place for every destination ([How many
destinations](../draft/routing.md#how-many-destinations)). A destination that changes its name
needs a second place in every relay until the first is forgotten network-wide. Forgetting is slow
by design:

* a relay that loses its route to a leaf asks once before it retracts it (routes to leaves,
  repaired patiently);
* a retraction is repeated `RETRACTS` times;
* a place is reused only once all of that has run its course.

Boards keep 1024 places (firmware#79), and `RELAY_PLACES` is 1024. In a network that fills them, a
rotation of every id at once needs twice that. Without it the new ids find no places, and the
network does not recover.

### Measured

Method, as for routing.md's own sweeps:

* the firmware's core at `76861e9` in the simulator;
* a thousand nodes over 18 km by 18 km, 200 relays;
* the board's tables unless a row says otherwise;
* the traffic `tools/density.py` gives the core: a message from each node every half hour, a
  quarter of them broadcast, four regular correspondents, a minute to arrive in;
* two seeds;
* the network let settle for 8 hours, then every node that rotates does so at once, retired as
  above;
* each hour after measured on its own.

EU868's settings are SF7 at 125 kHz ("fast"); US915's are SF9 at 500 kHz, what US boards ship.

Unicast on time, broadcast on time, and the network's seconds on the air, in the hour starting
`h` after the rotation:

With the board's 1024 places (each cell: unicast on time, broadcast on time, seconds on the air in
the hour, all nodes together):

| Rotation | `h` | EU868 (SF7, 125 kHz) | US915 (SF9, 500 kHz) |
|---|---|---|---|
| none | settled | 96.5%, 89.0%, 11 843 s | 98.5%, 92.9%, 9 608 s |
| every node at once, retired | 0 | 2.6%, 84.7%, 19 936 s | 3.2%, 90.3%, 16 533 s |
| | 1 | 4.5%, 91.8%, 13 597 s | 6.1%, 92.9%, 11 802 s |
| | 2 | 6.2%, 91.0%, 12 915 s | 7.5%, 93.3%, 8 584 s |
| | 3 | 6.0%, 91.6%, 10 310 s | 9.6%, 92.1%, 8 460 s |
| | 5 | 9.5%, 91.7%, 9 261 s | 27.5%, 92.3%, 8 456 s |
| every node at once, not retired | 0 | 2.3%, 87.1%, 17 617 s | 2.6%, 89.9%, 14 290 s |
| | 5 | 3.5%, 90.7%, 8 073 s | 3.7%, 92.4%, 6 690 s |
| leaves only, retired | 0 | 19.2%, 88.2%, 18 629 s | 21.5%, 90.8%, 15 299 s |
| | 5 | 22.5%, 90.1%, 11 486 s | 23.9%, 92.1%, 9 778 s |
| each node at its own time, daily | steady | 40.9%, 87.2%, 14 881 s | 43.4%, 90.6%, 12 164 s |
| each node at its own time, every 6 h | steady | 11.5%, 87.7%, 17 231 s | 12.4%, 90.4%, 14 413 s |

With room for every old name and every new one. 4096 places and 2048 gave identical results to the
last digit for every hour both were run (0 to 5), so twice the network's size is enough. Hours 8
on are from runs that rotate once. With nothing rotating, 4096 places give exactly what 1024 do:

| Rotation | `h` | EU868 | US915 |
|---|---|---|---|
| every node at once, retired | 0 | 7.7%, 85.6%, 20 157 s | 17.3%, 89.2%, 16 636 s |
| | 1 | 30.3%, 91.3%, 14 062 s | 43.1%, 92.9%, 12 266 s |
| | 2 | 50.6%, 90.2%, 14 360 s | 77.7%, 92.6%, 11 650 s |
| | 3 | 65.5%, 89.1%, 14 796 s | 77.5%, 92.7%, 13 360 s |
| | 5 | 85.2%, 89.2%, 13 926 s | 84.4%, 92.7%, 12 219 s |
| | 8 | 93.7%, 90.2%, 12 236 s | 94.3%, 91.9%, 10 590 s |
| | 11 | 94.4%, 89.5%, 11 858 s | 96.9%, 91.3%, 10 360 s |
| | 15 | 95.3%, 90.1%, 11 710 s | 97.2%, 91.1%, 10 196 s |
| the same, with the learning allowance opened again at the rotation | 0 | 12.9%, 85.7%, 21 227 s | 24.2%, 89.9%, 18 151 s |
| | 1 | 57.1%, 89.7%, 15 816 s | 69.0%, 92.0%, 14 106 s |
| | 2 | 59.1%, 88.7%, 16 549 s | 83.5%, 90.8%, 13 469 s |
| | 3 | 65.0%, 87.7%, 16 128 s | 75.6%, 90.2%, 13 910 s |
| | 5 | 70.4%, 88.6%, 14 823 s | 84.3%, 90.8%, 12 241 s |
| | 8 | 93.4%, 88.9%, 12 264 s | 97.7%, 91.8%, 10 077 s |
| leaves only, retired | 0 | 38.3%, 86.8%, 19 015 s | 51.9%, 90.4%, 15 802 s |
| | 1 | 72.3%, 88.4%, 14 071 s | 85.0%, 91.2%, 11 737 s |
| | 2 | 78.7%, 86.8%, 13 797 s | 85.7%, 90.2%, 11 895 s |
| | 3 | 77.5%, 87.4%, 14 074 s | 76.0%, 90.2%, 12 153 s |
| | 5 | 84.1%, 89.0%, 13 356 s | 78.7%, 91.4%, 11 737 s |
| each node at its own time, daily | steady | 67.3%, 85.9%, 15 742 s | 76.3%, 90.3%, 12 471 s |

Averaged over an epoch, rotating every `P` hours. The hours measured come first, then the
baseline's once a row is back within a point of it, or else the last hour measured:

Every node at once, with room for both names: unicast on time and seconds on the air an hour,
averaged over an epoch. Each hour of the epoch takes the value of the last hour measured at or
before it, and once that is within 1.5 points of no rotation, takes no rotation's. Broadcast is
within a point of no rotation throughout:

| `EPOCH` | EU868 | US915 |
|---|---|---|
| none | 96.5%, 11 843 s | 98.5%, 9 608 s |
| 6 hours | 50.8%, 15 350 s | 62.9%, 13 248 s |
| 24 hours | 83.4%, 12 939 s | 87.6%, 11 008 s |
| 7 days | 94.6%, 12 000 s | 96.9%, 9 808 s |

What these say:

1. **With the board's tables, rotating breaks routing.** Once every name has changed, unicast stays
   at 3 to 10% for at least five hours and does not recover in the time measured. Rotating only
   leaves gives about 22%, each node at its own time about 42%, and not retiring the old name 3%.
   The old names hold their places until their retractions have run their course, and the new
   ones find none.
2. **Twice the places is enough.** With 2048 the network recovers exactly as with 4096. Recovery
   then depends on the cap: every relay has a table's worth of new names to tell, at 0.5% of its
   time. It is back to 85% after five hours, and within a point and a half of no rotation after
   11 to 15.
3. **A daily rotation costs 11 to 13 points of unicast** (83.4% against 96.5% on EU868's
   settings, 87.6% against 98.5% on US915's) and 9 to 15% more airtime. **A weekly one costs about
   2 points** (94.6% and 96.9%) and 1 to 2% more airtime. Each rotation costs the network 26 to 34
   seconds on the air a node, over the 16 hours after it.
4. **Rotating at once is better than at each node's own time,** in privacy (R1 below) and in
   delivery: daily at each node's own time held 67 to 76% throughout, below the daily average of
   rotating at once.
5. **Opening the learning allowance again at the rotation** brings routes back faster in the
   first hour or two, but costs more airtime and is no better by hour five.
6. **Broadcasts do not notice:** floods follow no routes.
7. **Not measured: the slow preset** (SF8 at 62.5 kHz), where a network that starts together takes
   6 to 12 hours to learn its routes ([routing.md](../draft/routing.md#rationale), "A learning
   allowance"). A rotation there should cost at least as much again, and a daily one most of each
   day.

### Options for the rotation

| | Rotate | Anonymity across a rotation | Table cost | Measured |
|---|---|---|---|---|
| R1 | Every node at once (synchronised epoch) | Best: every name in the network changes in the same minute. Observer (a) must match old routes to new ones by their shape (which relays carry them, at what metrics). That is an assignment problem over the whole network, not one name at a time | Twice the places, for as long as the old names take to be forgotten | Rows "all" |
| R2 | Each node on its own timer | Poor against (a): one name disappears and one appears in the same part of the network within the same minute, so they are trivially matched | A few extra places at any time, if retired names free theirs promptly | Rows "spread" |
| R3 | Leaves only; relays keep stable public ids | Relays' owners give up their own privacy. Relays are infrastructure and seldom move, which makes them easy to locate anyway | Places for 800 of 1000 names twice | Rows "leaves" |

### Freeing places network-wide, measured

Requirement 1 below was then simulated. The firmware was given two ways of freeing a retired
name's place, both off and not specified (`ternmesh/firmware`, tag `experiment/retire-1`), and the
simulator ran them (`ternmesh/sim`, `tools/rotate.py`, sim#84):

* **Retired on the air.** A retraction marked *retired* (a listed metric of `0x7FFF`, which no
  route or retraction uses, so a node without the rule reads it as a retraction). A relay frees the
  place at once, passes the retirement on, and takes no route to the name for an hour after, so a
  neighbour not yet told cannot bring it back.
* **The epoch's places.** At the epoch's start every node marks the places it holds as old. With
  its table full, a new name takes an old place, one with no route selected first. Then, five
  minutes into the epoch (`epoch_grace`), every node forgets the neighbours it has not heard since
  the epoch began, and every route through them: every id has changed, so they will not be heard
  again under the ids they had. Nothing goes on the air for either.

In both, each neighbour of a rotating node hears the node's own retirement, a signed announce under
the old key, unless it is lost: "a fifth missing" has each neighbour miss it one time in five.

Method as above: 1000 nodes, 200 relays, the board's 1024 places, every node rotating at once, two
seeds. The slow preset (SF8 at 62.5 kHz) does not carry the default traffic even without a rotation
(16% unicast), so it was run with a message from each node every four hours and 16 hours to settle,
with which it does (96.8%). Unicast on time averaged over a weekly epoch:

| | EU868 (SF7, 125 kHz) | US915 (SF9, 500 kHz) | Slow (SF8, 62.5 kHz) |
|---|---|---|---|
| No rotation | 97.6% | 98.7% | 96.8% |
| Neighbours told only (the rows above) | 9.0% | 25.4% | — |
| Retired on the air, sent `RETRACTS` (3) times | 6.6% | 42.4% | — |
| Retired on the air, sent once | 95.5% | 96.6% | — |
| the same, a fifth missing | 92.3% | 56.1% | — |
| **The epoch's places** | **96.2%** | **97.4%** | 81.6% |
| the same, a fifth missing | **92.2%** | **97.4%** | 80.0% |
| the same, no retirement sent | 89.4% | 96.0% | 76.3% |
| *the epoch's places without forgetting neighbours, a fifth missing* | *85.1%* | *67.6%* | — |

With a daily epoch, the epoch's places give 87.7% and 90.2% on EU868's and US915's settings, and
58.8% on the slow preset.

What these say:

1. **Retirements on the air cost too much.** Every relay has a retirement to pass on for every name
   in the network, and sent as often as a retraction they take hours of its cap, ahead of the new
   names. Sent once, they free the places, but one lost from the start leaves the old name in use
   for `SILENT_MAX`: US915's settings fall to 56%.
2. **The epoch's places meet requirement 1 with the board's tables,** at no cost on the air. A
   weekly rotation costs 1.3 to 1.4 points of unicast on EU868's and US915's settings, against
   about 2 with twice the places before.
3. **Forgetting the neighbours the epoch left behind is what makes a lost retirement cheap.**
   Without it, a fifth missing cost 11 and 30 points more than none missing; with it, 4 and none.
   The node's own retirement still helps on EU868's settings (96.2% with, 89.4% without), so it is
   kept, but the network does not depend on it.
4. **The slow preset pays about 15 points a week.** It takes 6 to 12 hours to learn its routes
   ([routing.md](../draft/routing.md#rationale)), and is back to 85% only 11 hours after a
   rotation. A monthly epoch would cost roughly a quarter of that; not measured.
5. **Only for every node at once (R1).** The epoch's places assume every name changed at the
   boundary. A node that does not rotate has its place given up as readily, and is learned again.

### Requirements before rotation is turned on

1. **A retired destination frees its place at once, network-wide.** *Met by the epoch's places,
   measured above, rather than by a retraction marked retired.* The retirement should travel
   as a retraction marked *retired*, which every relay applies without the patient wait and passes
   on in its next announce, freeing the place as it does. That is a routing.md change, and it needs
   its own simulation, since a retraction lost on the air still leaves a stale route (routing.md
   says so of every retraction).
2. **Or room for both.** `RELAY_PLACES` at twice the network's size. A relay's place is 64 bytes,
   so 2048 places is 128 KB: past what an nRF52840 (256 KB of RAM, about 34 KB free on T1000-E)
   or a classic ESP32 has. Possible on an ESP32-S3 with PSRAM.
3. **A measured retirement.** The best case is modelled here. A real one is lost sometimes, and
   then the old name lingers for `SILENT_MAX`. *Measured above: with the neighbours left behind
   forgotten, a fifth lost costs 4 points more or fewer.*

Still to hold before rotation is turned on:

4. **An epoch every node agrees on.** A node with the wrong epoch is unreachable to its contacts.
   A node with no clock it trusts (a phone's `SET_TIME`, or GPS) does not rotate.
5. **Not on the slow preset,** or with a longer epoch there, measured first.
6. **The routing measured on radios.** Every number here is the simulator's.

Until then rotation should be specified, with its epoch byte, the epoch's places, the neighbours
forgotten, the node's own retirement and re-based counters, but **off**: `EPOCH` infinite, `e` =
0, which is exactly Part 1.

## Part 3: the other leaks

| Leak | Change | Cost | Recommended |
|---|---|---|---|
| Acknowledgement names the source, and shares the message's tag | None possible within the design: the relay before the destination ends its hop on hearing an acknowledgement it can match to the message, so a listener who heard both can match them too. Limit 3 above. Part 2 bounds it to an epoch, and Part 1 keeps the source's address out | None | State it |
| `message_1` names both ends | As above: `source` is where `message_2` must go. Part 1 keeps both addresses out; Part 2 bounds it to an epoch | None | State it |
| `hops` = `HOP_MAX` at the source | Start at `HOP_MAX - r`, `r` random in 0 to 3. The rule that a last-hop acknowledgement is from the destination only at `HOP_MAX` ([forwarding.md](../draft/forwarding.md#hops)) becomes "the first acknowledgement heard after the last hop". It helps only relays: a leaf never relays, so its frames are its own whatever `hops` says | None on the air | No: little gain, a rule changed |
| Flood `hops` = `FLOOD_HOPS` at the writer | Same reasoning: leaves do not pass floods on | None | No |
| `hdr` says whether a message is words or for the node (`0x48`/`0x49`, `0x60`/`0x61`) | Move the flag into the plaintext's first byte, encrypted. One byte more on a message of words, nothing on one for the node | About 1.5 ms per message at SF7/125 kHz (often 0, since time on air goes by symbols), 1.1 ms at SF9/500 kHz, 8 ms on the slow preset | **Yes**, cheap |
| Message length to the byte | Pad the plaintext to a multiple of 16 bytes | 8 to 11% more airtime on messages of 1 to 64 bytes, by Semtech's formula: 9.5% at SF7/125 kHz, 8.0% at SF9/500 kHz, 11.1% at SF8/62.5 kHz | As an option a user turns on, off by default |
| Frame kind (acknowledgement 19 bytes, first contact 56/60/80/24 bytes, own `hdr`) | None: relays treat them differently (last hop sent once) | — | State it |
| Requests name the destination wanted | Part 2 bounds it to an epoch | None | — |
| Solicits and answers name the leaf and its relays (movement) | Part 2 bounds it to an epoch | None | — |
| `number` and `seq` continue for ever | Re-based per epoch (Part 2) | None | With Part 2 |

## What each observer learns

| | Today | With Part 1 | With Parts 1 and 2 (`EPOCH` 7 days) |
|---|---|---|---|
| **(a) far** | Every routing id, fixed for life, and each one's address wherever anyone has heard its announces. Who writes to whom, as ids, for months. Topology | Fixed pseudonyms with no address. The who-writes-to-whom graph between pseudonyms, for months. Topology | Pseudonyms for a week. A graph per week, linked across weeks only by matching each week's routing structure, or by a side channel |
| **(b) near you** | Your address, id and neighbours, and the ids you write to (and, from their own announces, their addresses). Acknowledgements give who writes to you | Your pseudonym and neighbours, and the pseudonyms you write to and who writes to you; no addresses. Your radio, across time, by its signal (limit 2) | As Part 1 within a week. Across weeks, still your radio by its signal; your pseudonyms change |
| **(c) a relay** | As (b) for the frames it carries, plus routes to every destination | As (b) for what it carries, plus routes to every pseudonym | Per week |
| **(d) knows your address** | Your id: can spot every frame to or from you anywhere it listens | The same | The same, each week |

## Costs at a glance

| | Part 1 (blinded key) | Part 2 (rotation, weekly / daily) | Header flag | Padding |
|---|---|---|---|---|
| Airtime | 0 | +1 to 2% / +9 to 15%, and 1 byte an announce for the epoch | ~1 byte a text message | 8 to 11% of message airtime |
| Unicast on time | 0 | about -1.4 / -10 points (EU868), -1.3 / -8.5 (US915) with the epoch's places and the board's tables; about -15 / -38 on the slow preset | 0 | Small (longer frames) |
| Flash | < 1 KB | + < 0.5 KB (epoch, retirement), estimated | ~0 | ~0 |
| RAM | 64 B + 4 B a contact | + 4 B a contact (the previous id); one bit a place, with the epoch's places | 0 | 0 |
| Spec sections | routing, first-contact, cards, sharing | routing, forwarding, companion (epoch from clock) | unicast-security, groups | unicast-security, groups |

## Recommendation

1. **Adopt Part 1 now.** Sign announces with the blinded key `B_0` and make routing ids from it.
   It removes the address from the air at no cost in airtime or delivery, keeps everything
   signatures were added for, and makes the drafts' claims true. Fold the change into
   routing.md and first-contact.md, and correct cards.md and companion.md.
2. **Move the `node` flag into the ciphertext.** It costs one byte, and hides what kind of message
   a frame carries.
3. **Specify Part 2, and leave it off.** Specify the epoch's places and forgetting the neighbours
   the epoch left behind, not a retraction marked retired. Turn it on with an `EPOCH` of seven days,
   every node at once, once requirements 4 to 6 hold: it bounds following a pseudonym to a week for
   about 1.3 points of unicast. A daily epoch costs too much for what it adds over a weekly one.
4. **Offer padding as a user setting**, off by default.
5. **State the limits** (relays know destinations by pseudonym, a nearby radio is identifiable,
   replies name their destination, timing) in routing.md's and forwarding.md's "What an observer
   learns", and on the website.

## Method

* The simulator's `core` routing plugin was given an experimental `rotate_s`, with
  `rotate_leaves`, `rotate_spread` and `rotate_retire` (`include/tsim/core.h`). At a rotation a
  node takes a new address and id. It keeps everything else, as Part 2 says: the id is changed in
  place in the firmware's router state, its next `ADDRESS_AFTER` announces carry the new key, and
  Trickle is reset to `I_MIN`.
* A retirement is modelled as every neighbour that holds the old id forgetting it at that moment
  (`tern_route_lost()` with `DEAD_HOPS` of 1).
* The firmware's own code is otherwise unchanged. Nothing new goes on the air in the simulation:
  the retirement and the epoch byte are not counted, and both are small.
* For [Freeing places network-wide](#freeing-places-network-wide-measured), the firmware at
  `ternmesh/firmware` tag `experiment/retire-1` (`config.retire`, `tern_route_retire()`,
  `tern_route_epoch()`, `config.epoch_grace`), and the simulator's `rotate_retire` 2,
  `retire_repeats`, `retire_loss_ppm`, `rotate_epoch` and `epoch_grace_s`. The variants are
  `rotate.py`'s `all`, `net`, `net-once`, `net-once-loss`, `epoch`, `epoch-loss`, `epoch-forget`,
  `epoch-forget-loss` and `epoch-forget-silent`, the slow preset's with `--interval "4 h" --settle
  16`; the sim's `Sweep` workflow runs them.
* `tools/rotate.py` runs every row above (`--variants`, `--hours`). The first sweep measured hours
  0 to 5; hours 8, 11 and 15, and the learning allowance's rows, were run afterwards with
  `rotate_count` 1, so the epoch table above was put together from the hour tables by hand, by
  the rule stated there. The firmware's numbers and seq continue across a rotation in the
  simulation, which does not change what it costs.

## References

* RFC 8966 (Babel) and RFC 6206 (Trickle): as in [routing.md](../draft/routing.md#rationale).
* Tor Project, *Tor Rendezvous Specification - Version 3* (rend-spec-v3), appendix A.2, key
  blinding.
* N. Hopper, *Proving Security of Tor's Hidden Service Identity Blinding Protocol*, 2013.
* F. Denis, E. Eaton, T. Lepoint, C. A. Wood, *Key Blinding for Signature Schemes*, IRTF CFRG
  Internet-Draft draft-irtf-cfrg-signature-key-blinding.
* Bluetooth Core Specification, Vol 3 Part C, 10.8: resolvable private addresses.
* A. Perrig, R. Canetti, J. D. Tygar, D. Song, *Efficient Authentication and Signing of Multicast
  Streams over Lossy Channels* (TESLA), IEEE S&P 2000.
* G. Danezis, I. Goldberg, *Sphinx: A Compact and Provably Secure Mix Format*, IEEE S&P 2009.
* V. Brik, S. Banerjee, M. Gruteser, S. Oh, *Wireless Device Identification with Radiometric
  Signatures*, MobiCom 2008.
