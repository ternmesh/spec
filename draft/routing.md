# Routes

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It is the design
the simulator ([ternmesh/sim](https://github.com/ternmesh/sim),
candidate 3) was measured with, written down, and every number in it is
**provisional**: a default the simulator settled on, not one measured on
radios (see [Not yet measured](#not-yet-measured)).

This section defines how a node learns which neighbour to hand a frame
to for each node it can reach: the frames nodes announce themselves and
their routes with, how a node judges its links, and how it chooses,
keeps and repairs routes. The frames that *follow* those routes are
[their own section](forwarding.md).

Test vectors: [`vectors/routing.json`](../vectors/routing.json),
produced by [`vectors/tools/routing.py`](../vectors/tools/routing.py).

## Goals

1. **Routes, not floods.** A unicast frame is sent once per hop, along
   a route the network already holds. The simulator delivered 89 to 97%
   of unicast messages on time over a thousand nodes this way, against
   53% at best for the flooding designs it compared.
2. **Never a loop.** Routes change while frames are in flight. No
   change, however it is delayed or lost, may send a frame round in a
   circle. Between nodes that keep their state this is exact. A node
   that restarts has lost it, and what stands in for it is a wait (see
   [Starting](#starting)).
3. **A bounded share of the channel.** What a node spends on routing is
   capped, whatever happens around it.
4. **Quiet when nothing changes.** A network at rest announces rarely;
   one that is changing announces soon.
5. **Links that work both ways.** LoRa links are often one-way. A node
   uses a neighbour only once each has shown it hears the other.
6. **A few kilobytes.** A node keeps at most four routes for each node
   it knows of, and no timer for any of them.

## Notation

As in [unicast-security.md](unicast-security.md#notation). Every number
on the air is big-endian. In frame layouts, `u8`, `u16` and `u32` are
unsigned and `i8` is a signed byte. `Sign` and `Verify` are Ed25519 as
[Presence cards](cards.md#notation) has them, under the node's
[identity key](first-contact.md#addresses).

Sequence numbers are 16 bits and wrap. `a` is **newer** than `b` if
`(a - b) mod 2^16` is between 1 and `0x7FFF`.

`airtime(L)` is the [time on air](phy.md#time-on-air) of a frame of `L`
bytes on the node's profile.

The values this section names in `CAPITALS` are in
[Parameters](#parameters).

## Routing ids

Routing knows a node by a four-byte **routing id**, not by its
[address](first-contact.md#addresses) `A`:

```
H       = SHA-256("tern routing id" || A)
rid(A)  = the first of H[0..4], H[4..8], ... H[28..32], as a u32,
          that is neither 0x00000000 nor 0xFFFFFFFF
```

`0xFFFFFFFF` means every neighbour. `0x00000000` is never used. (That
all eight are reserved has probability 2^-248.)

## Roles

A node is a **relay** or a **leaf**. Only relays forward other nodes'
frames and announce other nodes' routes. A leaf announces itself, and
what it hears, and nothing else. Which a node is, is its owner's choice
for now. A node may **use** a neighbour as the next hop to a
destination only if the link to it is [up](#links), and the neighbour
is a relay or is the destination itself.

## Announces

A node's one periodic frame:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | `0x59` |
| 1 | 4 | `sender` | the sender's routing id |
| 5 | 2 | `number` | counts the sender's announces |
| 7 | 2 | `seq` | the sequence number of the sender's route to itself |
| 9 | 1 | `flags` | bit 0: the sender is a relay. Bit 1: it is [starting](#starting). Bit 2: the address follows. The rest are 0 |
| 10 | 2 | `promise` | the longest the sender may go before its next |
| 12 | 2 | `round` | announces it takes the sender to name every neighbour |
| 14 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |
| 15 | 1 | `h` | how many neighbours follow |
| 16 | 1 | `r` | how many routes follow |
| 17 | 32`a` | `address` | the sender's [address](first-contact.md#addresses), if bit 2 of `flags` is set |
| 17 + 32`a` | 5`h` | neighbours | each `id` `u32`, `margin` `u8` |
| 17 + 32`a` + 5`h` | 8`r` | routes | each `destination` `u32`, `seq` `u16`, `metric` `u16` |
| then | 64 | `sig` | |

`hdr` has format `01` (draft 0), type `011` (routing) and flags `001`
(announce). `a` is 1 if bit 2 of `flags` is set and 0 otherwise. The
frame is exactly `81 + 32a + 5h + 8r` bytes, and at most 255. A
receiver MUST discard one of any other length, one whose `sender` is
its own id or a reserved id, and one whose `flags` has an unknown bit
set.

```
M    = "tern v0 announce" || the frame up to sig
sig  = Sign(sk, M)
```

### Signed

An announce is signed by its sender, and a node takes nothing from one
it cannot check. For each neighbour a node keeps that neighbour's
address, once it has one, and forgets it with the neighbour. On
hearing an announce, after the checks above, a node:

1. if the announce carries an address, MUST discard it unless the
   address is [valid](first-contact.md#addresses), `rid` of it is
   `sender`, and it is the address the node holds for `sender`, if it
   holds one. This comes before the signature, as for a
   [card](cards.md#receiving);
2. MUST discard it if it carries no address and the node holds none for
   `sender`: there is nothing to check it with;
3. MUST discard it unless `Verify(address, M, sig)` passes, with the
   address carried or held;
4. holds the address for `sender`, if it did not, and takes the
   announce as the rest of this section says.

A frame discarded here is not heard at all: it is no sample for a
floor, no sign of life, and no inconsistency.

**Carrying the address.** A node MUST carry its address in every
announce while it is [starting](#starting); in each of the
`ADDRESS_AFTER` announces after it finds a neighbour, which may not
hold it; and in at least one of every `ADDRESS_EVERY` announces, for a
neighbour that missed those. It MAY carry it in any other. It is 32
bytes a frame, so a node that carries it when no neighbour needs it
spends airtime on nothing.

Requests are not signed: see [Not yet specified](#not-yet-specified).

**`number`** goes up by one with each announce sent, across restarts
too: a node MUST NOT send an announce whose `number` is not newer than
that of the last announce it sent with its address, before a restart
or since. So it keeps a number `kept` where a restart does not lose it.
It never sends an announce numbered `kept` or newer: before it would,
it stores a later one in its place, `NUMBER_SAVE` later once an
announce has gone on the air since it started, and one later until
then. On starting it numbers its first announce `kept`. A node MUST keep `kept` for as long as it keeps its identity key,
and lose them together. A node that has never kept one starts from a
random value; its neighbours from before, if it had any, may discard
its announces until they [forget](#links) it.

**`promise`** is in seconds up to 32767; with the top bit set, the low
15 bits are minutes, up to 32766; `0xFFFF` is no promise. It is rounded
up. A node computes it as the sum of: what is left of its current
[interval](#when-to-announce); the next `QUIET_MAX + 1` intervals, each
twice the last up to the longest; the time [the cap](#the-cap) takes to
pay for a 255-byte frame; and the longest any of its last few announces
waited between being built and going on the air.

**Neighbours.** A node names the neighbours whose announces it hears, at
most `NAMED_MAX` to a frame: first those it has not yet named at all,
then the rest in turn from where its last frame stopped. `round` is how
many frames that takes: the number of neighbours over `NAMED_MAX`,
rounded up. `margin` is [below](#links).

**Routes.** A relay lists routes it has [selected](#selecting-a-route):
the destination, the sequence number the route carries, and the route's
metric from this node. A metric of `0xFFFF` **retracts** the route. Its
route to itself, metric 0 at `seq`, is implied and never listed. Routes
that have changed since they were last announced go first; the rest
follow in turn, as many as fit, so that every route is repeated every
so many announces. A leaf lists none.

## Links

A **neighbour** is a node whose announces this node hears. For each, a
node keeps:

**Its floor**: the quietest this node could send and still be heard by
it, reckoned from how well the neighbour's own frames arrive, the
channel's loss being the same both ways on average. On hearing an
announce sent at `power` with signal-to-noise ratio `snr`,

```
sample = power - (snr - SNR_FLOOR)
floor  = sample                          for the first
floor  = (3 floor + sample) / 4          after
```

`SNR_FLOOR` is `-7.5 - 2.5 (SF - 7)` dB. The floor is kept in sixteenths
of a decibel, and the division rounds down.

**What it says of this node.** When a neighbour's announce names this
node, the `margin` it gives is how far below its own full power the
neighbour's floor for this node lies: `full power - floor`, in whole
decibels rounded down, plus 128, and kept between 1 and 255. So 128 is
no margin at all, and a neighbour never says 0.

A neighbour stops hearing a node without saying so. If a neighbour has
sent `NAMED_ROUNDS` × max(`round`, 1) + 1 announces or more, by their
`number`, since it last named this node (never counting more than
`0x7FFF`), this node MUST take the margin it gave as withdrawn.

**The link's margin** is the lesser of this node's `full power - floor`
and the margin the neighbour gave, and is undefined while either is
missing. The link is **up** once its margin is `LINK_MARGIN` or more,
and stays up until it falls more than `LINK_BAND` below that, or the
neighbour's margin is withdrawn.

A node MUST forget a neighbour, and every route through it, once it has
heard nothing from it for `SILENT_MAX` and for two of its promises. A
neighbour whose last announce made no promise is not forgotten for its
silence, however long: it said it could not tell how long it would be.
Silence is otherwise no signal here, announces being lost too often for
it to be one. What tells of a neighbour that has gone is
[frames sent to it and lost](forwarding.md#hops).

**Numbers out of order.** An announce whose `number` is not newer than
the last from the same sender is a copy, is late, or is recorded and
sent again, and is discarded whole, however long the sender has been
silent. That an announce says its sender is [starting](#starting) does
not excuse its number.

**Neighbours forgotten.** Forgetting a neighbour forgets its last
`number`, and with it what would tell a recording of it from a new
announce. So a node SHOULD keep, for at least the last `FORGOTTEN_KEPT`
neighbours it forgot, the routing id and the last `number`, and MUST
discard an announce from one of them that is not newer than that
number, as from a neighbour it keeps. One that is newer is taken as
from a neighbour just found, and its entry dropped.

**A full table.** A node keeps as many neighbours as it has room for,
and where there are more nodes to hear than that, which ones it keeps
decides whether it has routes at all. On hearing an announce from a
node it does not keep, with no room left, a node looks at the
neighbours whose links are not up. If the floor the announce gives is
`REPLACE_BAND` or more below the highest floor among them, the node
MUST forget that neighbour, and every route through it, and keep the
sender in its place; of two with that floor, either. Otherwise it MUST
take nothing from the announce. A node MUST NOT replace a neighbour
whose link is up.

### Power for every neighbour

A frame meant for every neighbour, as an announce is, goes only as loud
as the nearest few need. With the floors of at least `POWER_K`
neighbours known, a node sends such frames at the `POWER_K`-th lowest
of them plus `POWER_MARGIN`, rounded up to a whole dBm and kept between
its lowest power and its full power. With fewer, at full power.

A frame for one neighbour, as a request can be, goes at that
neighbour's floor plus `POWER_MARGIN`, rounded and kept likewise, and
louder by the neighbour's boost, which
[frames sent to it and lost](forwarding.md#hops) raise.

## Routes

### The metric

A link that is up costs `LINK_COST`: `airtime(REF_LEN)` in
milliseconds, rounded up. A route's metric is the metric its neighbour
announced plus the link's cost, never more than `0xFFFE`. Every link on
a profile costs the same, so the metric counts hops in units of time on
air.

### What a node keeps

For each destination, a node keeps at most `ROUTES_KEPT` routes, each
through a different neighbour: that neighbour's latest `seq` and
`metric` for the destination. An announce from a neighbour gives:

* a route to the sender itself, with the announce's `seq` and metric 0;
* if the sender is a relay, each route it lists. A node MUST ignore
  routes listed by a leaf.

A retraction removes the route through that neighbour. A route to the
node's own id is ignored.

With no room for a new route, it replaces the least worth keeping of
those not selected, if it is worth more: a route the node could select
now is worth more than one it could not, then a newer `seq`, then a
lower metric.

Routes do not expire. A route lasts until its neighbour retracts it or
is forgotten.

### How many destinations

A relay can pass a frame on only toward a destination it keeps routes
for, so a network can be no larger than its relays' tables. A relay
SHOULD have places for `RELAY_PLACES` destinations. A leaf passes no
frame on, and needs places only for the destinations it sends to when it
takes [a default route](#a-leafs-default-route); a leaf MAY have as few
as `LEAF_PLACES`. With more destinations than places, a node keeps the
first it is told of and is told of the rest again when they change. A
network of more nodes than `RELAY_PLACES` is not specified yet (see [Not
yet specified](#not-yet-specified)).

### A leaf's default route

A leaf that has no route it may use to a destination MAY hand a frame
for it to its **nearest relay**: of the relay neighbours it may use
whose links are up, the one with the lowest floor, and of those with
equal floors, any. It MUST NOT:

* while it is [starting](#starting);
* while its busy share, as [flooding](flooding.md#a-busy-relay) has a
  relay's, is `DEFAULT_BUSY` or more. A leaf keeps the share as a relay
  does;
* to a neighbour the frame has been given up at, when it looks for
  [another way](forwarding.md#hops).

The relay's own route takes the frame on. A relay never takes a default
route, so no frame can go back to a leaf but the one it is for, and none
can loop. Where [forwarding](forwarding.md) and [first
contact](first-contact.md) say what a node with no route does, a leaf
that takes default routes and has a nearest relay it may hand the frame
to has a route; a leaf that takes none, or has no such relay, has none,
and asks for one. For the frame's [waits](forwarding.md), the route's
metric is `DEFAULT_HOPS` times `LINK_COST`, never more than `0xFFFE`.

### Selecting a route

For each destination a node keeps a **feasibility distance**: the best
(`seq`, metric) it has itself ever announced, where a newer `seq` is
better, and at the same `seq` a lower metric. A route is **feasible**
if the node has no feasibility distance for the destination, or the
route's `seq` is newer than its `seq`, or equal with a metric (as the
neighbour announced it) strictly lower.

A node MUST NOT select a route that is not feasible, nor one through a
neighbour it may not [use](#roles). Among the rest, it selects the one
with the lowest metric, but keeps the route it has selected unless
another's metric is lower by more than `HYSTERESIS` of it.

When a node announces a selected route, it sets the feasibility
distance to what it announces, if that is better.

### What a node announces

The metric a node announces for a route is the route's metric, except
that while the `seq` is the one it last announced and the metric is
within `CHANGE` of the metric it last announced, and that metric is
above the neighbour's, it announces that metric again.

A route has **changed**, and goes first in the next announce, when it
is first selected; when its `seq` is newer than the last announced;
when its metric differs from the last announced by more than `CHANGE`
of it; and when it is lost.

A node that loses its selected route to a destination it has announced
retracts it. A retraction lost on the air would leave a neighbour with
the route for good, so it goes in `RETRACTS` announces: once as a
change, then in turn with the routes, never twice in one frame.

### Starting

A node that starts has lost its feasibility distances, which are what
keep it from selecting a route that leads back through itself: its
neighbours may hold routes it announced before, and no longer knows of.
So for its first `START_ANNOUNCES` announces a node is **starting**:

* it sets the starting flag in its announces, and lists no routes;
* it selects no route but one whose neighbour is the destination;
* its announces are not suppressed, and its interval does not double.

A node that hears a neighbour say it is starting, in an announce whose
`number` is newer than the last, when that neighbour's last announce
did not say so, forgets the neighbour and every route through it, and
takes the frame as from a neighbour it has just found. It MUST
ignore routes listed in an announce that says its sender is starting.

### Starving, and asking

A node with routes to a destination, none of them feasible, is
**starved**: only a newer `seq` can help it, and only the destination
can make one.

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | `0x5A` |
| 1 | 4 | `next` | the neighbour asked, or `0xFFFFFFFF` for all |
| 5 | 1 | `n` | how many requests follow, at least 1 |
| 6 | 7`n` | requests | each `destination` `u32`, `seq` `u16`, `hops` `u8` |

`hdr` has type `011` and flags `010` (request). The frame is exactly
`6 + 7n` bytes. A node acts on a request frame only if `next` is its id
or `0xFFFFFFFF`.

A starved node asks for a `seq` one newer than its feasibility
distance's, or the newest any of its routes carries if that is newer
still, with `hops` of `HOP_MAX`. It asks the neighbour whose infeasible
route is best among those it may use, or every neighbour if it may use
none. A node that has no feasibility distance for the destination has
nothing to be newer than: it asks every neighbour, with `seq` 0 and
`hops` 0.

It asks at once unless it asked within `REQUEST_INTERVAL`, and again
every `REQUEST_INTERVAL` until it has a route, `REQUEST_TRIES` times in
all.

A node that receives a request:

* **with `hops` 0:** if it is the destination, or is a relay with a
  selected route to it, announces soon (below), with that route as a
  change. Otherwise it does nothing.
* **for itself:** if the `seq` asked for is newer than its own, takes
  that `seq` as its own. Either way its next announce is not
  suppressed, and comes within the shortest interval.
* **for another, as a relay:** if it has a selected route whose `seq`
  is as new as asked, announces soon with that route as a change.
  Otherwise, if it has a selected route, `hops` is more than 1, and it
  has not sent on a request for the same `seq` within
  `REQUEST_INTERVAL`, it sends the request on to that route's
  neighbour, with `hops` one fewer.

A leaf does nothing with a request for another node.

Requests for the same `next` share a frame. A request waits a random
time up to `JITTER` × `airtime(62)` before it goes, so that nodes that
heard the same frame do not answer at the same instant.

**A node that restarts** and has not kept its `seq` starts from any
value. Its neighbours then hold routes at its old `seq`, starve, and
ask for a newer one, which it takes. A node SHOULD keep its `seq`
across restarts.

## When to announce

Announces are timed by Trickle (RFC 6206). A node's interval starts at
`I_MIN` and doubles, when it ends, up to `I_MAX`. In each interval the
node picks a random time in its second half, and announces then unless
it has heard `REDUNDANCY` or more **consistent** announces since the
interval began. An announce heard is consistent unless it changes
something this node announces: a route gained, lost or
[changed](#what-a-node-announces), or a neighbour found, forgotten,
changing its role, or its link going up or down.

Anything that does is an **inconsistency**: if the interval is longer
than `I_MIN`, a new interval of `I_MIN` begins at once. To **announce
soon** is the same.

Departing from RFC 6206:

* An announce is never suppressed while the node has changed routes
  waiting, or a request for its own `seq` to answer.
* An interval that ends with changed routes still waiting does not
  double.
* A request that makes a node take a newer `seq` begins a new interval
  of `I_MIN` even if the interval already is `I_MIN`.
* A node that has been suppressed in `QUIET_MAX` intervals running
  announces in the next whatever it has heard.

## The cap

Announces and requests together take no more than `CAP` of a node's
time: `REQUEST_SHARE` of it for requests, the rest for announces. Each
is a token bucket, which fills at its share and holds `CAP_WINDOW` of
it, or one 255-byte frame if that is more, and starts full.

A node builds an announce only when the announces' bucket holds the
airtime of the longest frame it could come to; otherwise the announce
waits until it does. The frame is charged what it actually takes. When
its time comes, a node may send up to `BURST` announces, one after
another, while changed routes remain and the bucket allows.

A request frame the requests' bucket cannot pay for is dropped. A
starved node asks again anyway.

## Parameters

| Name | Value | |
|---|---|---|
| `I_MIN` | 8 s | the shortest interval |
| `I_MAX` | 512 s | the longest: six doublings |
| `REDUNDANCY` | 3 | consistent announces that suppress one |
| `QUIET_MAX` | 2 | intervals a node may be suppressed running |
| `CAP` | 0.5% | of a node's time, for routing |
| `REQUEST_SHARE` | 1/4 | of the cap, for requests |
| `CAP_WINDOW` | 60 s | |
| `BURST` | 4 | announces at one time, at most |
| `NAMED_MAX` | 8 | neighbours named in a frame |
| `NAMED_ROUNDS` | 8 | rounds a margin outlasts |
| `LINK_MARGIN` | 0 dB | |
| `LINK_BAND` | 3 dB | |
| `SILENT_MAX` | 24 h | |
| `REPLACE_BAND` | 6 dB | nearer a node must be to take a place |
| `POWER_K` | 8 | neighbours a frame for all should reach |
| `POWER_MARGIN` | 10 dB | |
| `REF_LEN` | 32 bytes | the frame the metric is reckoned in |
| `LINK_COST` | 70 ms on `US915`, `AU915` and `NZ915`, 81 ms on `EU868` | |
| `ROUTES_KEPT` | 4 | for each destination |
| `HYSTERESIS` | 1/10 | |
| `CHANGE` | 1/4 | |
| `RETRACTS` | 3 | |
| `START_ANNOUNCES` | 4 | announces a node is starting for |
| `REQUEST_INTERVAL` | 10 s | |
| `REQUEST_TRIES` | 5 | |
| `HOP_MAX` | 32 | |
| `JITTER` | 2 | airtimes |
| `RELAY_PLACES` | 1024 | destinations a relay keeps routes for |
| `LEAF_PLACES` | 32 | the fewest a leaf may keep |
| `DEFAULT_HOPS` | 6 | a default route's metric, in links |
| `DEFAULT_BUSY` | 50% | of a leaf's time, past which it takes no default route |
| `ADDRESS_AFTER` | 3 | announces that carry the address after a neighbour is found |
| `ADDRESS_EVERY` | 8 | announces of which at least one carries it |
| `NUMBER_SAVE` | 256 | announce numbers a node stores ahead |
| `FORGOTTEN_KEPT` | 64 | forgotten neighbours whose numbers a node keeps |

## Conformance

An implementation conforms to this section if, for
[`vectors/routing.json`](../vectors/routing.json):

* **ids:** given `address`, it derives `id`;
* **newer:** it finds `a` newer than `b`, or not, as `newer` says;
* **promises:** it encodes `seconds` as `code`, and reads `code` as
  `read_seconds` (`null` for no promise);
* **announces** and **requests:** it builds `frame` from the fields
  given, an announce signed with `seed`, and reads the fields from
  `frame`;
* **rejected:** it discards each `frame`, whether or not it holds the
  sender's address;
* **verified:** holding `held_address` for the sender of the announce
  given (`null` for none), it takes the announce or discards it as
  `takes` says, and then holds `holds_address`;
* **floors:** hearing announces at each `power` and `snr_quarter_db` in
  turn, at `spreading_factor`, it holds each `floor_sixteenths`, and
  with `full_power` names the neighbour with each `margin`;
* **links:** from down, with its own margin and the neighbour's as
  given at each step, it holds the link `up` or not;
* **named:** it takes a margin as withdrawn, or not, as `withdrawn`
  says, when the neighbour last named it in announce `named` and has
  now sent `number`, with `round`;
* **places:** with the full table of `neighbours` given, hearing an
  announce that gives `floor_sixteenths` from a node not among them, it
  replaces `replaces` (`null` for none);
* **numbering:** hearing an announce numbered `number` from a
  neighbour whose last was `last`, it does as `does` says: `take` it,
  `discard` it, or forget the neighbour and take it as found `again`.
  `starting` says whether the announce says its sender is starting, and
  `was_starting` whether the neighbour's last did;
* **costs:** for each profile, a link costs `link_cost`;
* **feasible:** with the feasibility distance given (`null` for none),
  it finds each route feasible or not;
* **selection:** with the routes given, each through a neighbour it may
  use, and `selected` naming the one selected before (`null` for none),
  it selects `selects`;
* **kept:** with four routes held and `selected` among them, offered
  `offered`, it replaces `replaces` (`null` for none);
* **defaults**, for an implementation that takes default routes: with
  the `neighbours` given, each a relay or not and each with its floor
  and whether its link is up, as a leaf or not (`leaf`), starting or
  not, with the busy share `busy_ppm`, and with the neighbours `tried`
  already tried at, it hands a frame with no route to `next` (`null` for
  none), with a route metric of `metric` on a profile whose links cost
  `link_cost`.

When announces go, and what a node does on a request, depend on random
times and cannot be checked by vectors. They are checked by running
implementations against each other and against the simulator.

## Rationale

**Distance-vector, with Babel's feasibility condition.** Routes are
learned from neighbours' announces, as in any distance-vector protocol,
and kept loop-free as Babel (RFC 8966) keeps them: a node only selects
a route strictly better than the best it has ever announced, so no
route it selects can lead back through a node that learned the route
from it. The cost is starvation, a node holding routes it may not use,
and the cure is the destination's sequence number, which only it can
raise. The design is written from RFC 8966, RFC 6206 and De Couto et
al.'s ETX paper, and not from any implementation.

**Departures from Babel.** A node keeps four routes for a destination,
not one per neighbour; routes have no expiry timers; there are no
hellos or IHU messages of their own, everything riding on the announce;
and the metric a node announces is sticky, so that noise in a metric
does not drag the feasibility distance down to its luckiest moment and
starve everyone downstream.

**Links by strength, not by counting.** Babel and ETX judge a link by
the share of hellos that arrive. On a loaded LoRa channel that measures
the load, not the link: in the simulator, routes' metrics rose with
traffic, failed feasibility and starved the nodes behind them. Judged
by signal strength each way, no link went down for want of it, and
unicast on time over a thousand nodes went from 23% to 50% at 0 dBm and
from 8% to 52% at 20 dBm.

**A margin of zero.** A link is used as soon as each end hears the
other at all. Asking for 3 dB to spare cost the sparsest networks
their only links: without it, unicast at the simulator's lowest power
went from 43% to 57%.

**Every link costs the same.** With one modulation on a profile the
metric counts hops. It is kept in time on air so that links on faster
or slower settings, when the MAC allows them, compare without changing
the frames.

**Power for the nearest eight.** A node in a crowd is heard by
hundreds at full power, and takes the channel from all of them each
time it announces. Reaching its eight nearest keeps the network
connected (Blough et al., the k-neighbours protocol) and leaves the
rest of the channel alone. Without it, the simulator's dense scenarios
spent their airtime on announces.

**Trickle, and a cap as well.** Trickle makes a quiet network quiet,
but a network that will not settle announces at `I_MIN` for ever. The
cap bounds that. The two buckets are apart so that a node asking about
many routes cannot spend what it needs to be heard at all.

**Eight rounds before a margin is withdrawn.** Two cut thousands of
good links an hour in the simulator: most frames are lost under load,
and two in a row often enough.

**A promise in every announce.** With Trickle a neighbour's silence
means nothing by itself: it may be suppressed. The promise says how
long silence is still ordinary.

**Four-byte routing ids.** A route costs eight bytes in an announce,
and a signed frame holds 21. With the 32-byte address it would hold
four. A hash of the address rather than its first bytes, so that a
route names a destination without giving its address away. A node's
own address does go on the air, to its neighbours: see
[Signed](#signed) and [What an
observer learns](#what-an-observer-learns). Two nodes in four billion
pairs share an id; see below.

**Big-endian**, as the rest of the specification is. The simulator's
frames are little-endian.

**Starting.** The simulator's nodes never lose their state. A real one
does, and Babel's condition rests on a node remembering what it has
announced. The exact cure is to remember across a restart, which means
writing to flash each time a feasibility distance changes; the one here
is AODV's (RFC 3561, section 6.13): say so, and wait. A neighbour that
hears any one of the starting announces drops what it held through the
node, and the node selects nothing through a neighbour until it has
sent them all. A neighbour that hears none of the four still holds its
old routes, and a loop through it is possible until it hears a fifth.
In the reference implementation's tests, with a third of announces lost
and a node in twelve restarting every hundred seconds, three runs of
five had no loop at all, and the longest loop in the others lasted 82
seconds; without the wait, loops lasted about three minutes.

**Why the nearest are kept, and links that are up never given up.**
A board has room for tens of neighbours, and in a town a node at full
power is heard by hundreds. Keeping whichever came first fills the
table with nodes too far off to hear back, or too busy with nearer ones
to name this node, and no link comes up. In the simulator, a thousand
nodes with 200 relays among them and 32 places each (three seeds), the
share of pairs of nodes holding a route once settled was 64% at SF7
and 17% at SF8 on 62.5 kHz keeping the first heard, and 88% and 82%
under this rule; with 64 places 93% and 77% against 96% and 91%; with
255, 97% and 92% either way. Letting a nearer node take the place of a
link that was up, on one seed with 64 places at SF8, left 91.5% of
pairs holding a route and 88.8% holding one that arrived, with requests
that never stopped, against 91.4% for both and no requests. Preferring
relays, or keeping half the places for them, held fewer routes than
taking no account of role: 23% and 84% at SF7 with 32 places, against
88%, on one seed.

**How many destinations, and a leaf's default route.** A network's size
is its relays' tables. The simulator, measured as a
board runs the firmware (its tables read from the firmware's source),
gave every node of a thousand-node region 128 places, as the firmware's
boards had them: 12% of pairs of nodes held routes that arrived, at SF7
and at SF8 on 62.5 kHz alike, and 12.5% of unicast messages arrived on
time, against 96% at SF7 with a place for every node. A node with 512
places reached 49% of the others, and 256 reached 25%: with more nodes
than places, a node reaches as many as it has places for. Limiting each
node to four peers changed nothing, since a relay passes on frames for
everyone's peers.

Relays alone need the places. With 200 relays among the thousand, at
SF7 (two seeds, a quarter of messages broadcast), relays of 1024 places
and leaves of 128 delivered 30% of unicasts on time, the leaves reaching
only what their own tables held; with the default route, leaves of 128
delivered 92.4% and leaves of 32, 93.0%, against 93.7% with 1024 places
everywhere. Relays of 512 delivered 49%. A relay's place is 64 bytes in
the firmware, so `RELAY_PLACES` is 64 kilobytes, and a leaf's
`LEAF_PLACES` two.

On a full channel the default route did harm. At SF8 on 62.5 kHz, where
every design the simulator ran lost most of what it sent, leaves of 32
places with the default route delivered 12.5% of unicasts on time and
0.5% of broadcasts, against 15.5% and 40% without it. With leaves of 128
(seed 1) they sent 4.2 times the data frames, and gave up as many
messages. The waste is in the retries of messages that
cannot arrive, not in trying a second relay, which changed nothing.
Holding the default route back while a leaf's radio is busy, relays of
1024 places and leaves of 32 (two seeds):

| `DEFAULT_BUSY` | SF7 unicast | SF7 broadcast | SF8 unicast | SF8 broadcast |
|---|---|---|---|---|
| none taken | 22.9% | 84.7% | 15.5% | 40.0% |
| 10% | 35.8% | 84.8% | 15.6% | 38.2% |
| 20% | 60.6% | 82.1% | 17.8% | 33.9% |
| 30% | 80.0% | 81.6% | 20.1% | 29.2% |
| 50% | 92.6% | 80.0% | 24.0% | 14.5% |
| always | 93.0% | 81.2% | 12.5% | 0.5% |

Leaves at SF7 among a thousand nodes are busy a fifth to a half of the
time, so a share much under a half costs them their routes. At a half
it costs them nothing, and at SF8 it delivers 84% of the unicasts that a
place for every node does (28.5%), with four times its broadcasts
(3.6%). `RELAY_PLACES` covers the thousand nodes these runs had; the
`SF7` rows are the closer to this specification's profiles, whose
symbols are as long.

**Signed announces, not a network key.** Unsigned, any radio can send
an announce in another node's name: list routes it does not have, claim
to be a destination and draw its frames, say a neighbour is
[starting](#starting) so that every route through it is dropped, or
name a node with a margin it never gave. With a signature, only the
holder of an address can say anything as the routing id made from it,
and a node takes no announce it cannot check. Meshtastic signs none of
its routing; MeshCore signs its adverts with Ed25519 and carries the
public key in each.

The alternatives considered:

* **A key the network shares**, as Meshtastic's channels have, keeps
  out radios without it and no one with it, and Tern has no network to
  share one: anyone may join.
* **A key for each neighbour**, from the X25519 key every address
  gives, authenticates frames sent to one node. An announce is for
  every neighbour, and a tag for each would cost more than a signature.
* **Keys disclosed later** (TESLA, a chain of hashes that each announce
  reveals one more of), at 16 to 32 bytes a frame, cost almost as much
  airtime as a signature in the runs below, and hold every route an
  announce brings until the next announce, up to `I_MAX` later.

A signature costs 64 bytes a frame. In the simulator, a thousand nodes
with 200 relays, relays of 1024 places and leaves of 32 with the
default route (two seeds), adding that many bytes to every announce
and request:

| Bytes added | SF7 unicast | SF7 broadcast | SF8 unicast | SF8 broadcast |
|---|---|---|---|---|
| 0 | 93.0% | 80.9% | 24.5% | 13.5% |
| 16 | 90.9% | 81.6% | 22.6% | 15.2% |
| 32 | 88.5% | 80.1% | 21.4% | 21.0% |
| 64 | 90.7% | 81.6% | 18.1% | 27.5% |
| 96 | 86.3% | 79.5% | 13.3% | 31.6% |
| signed, as here | 90.1% | 80.4% | 14.6% | 32.3% |

The last row is the firmware's router, signing as this section says,
with the address carried by `ADDRESS_AFTER` and `ADDRESS_EVERY`. At
SF7 the difference between seeds is as large as the cost of a
signature. At SF8 on 62.5 kHz, where the channel is full, signing costs
two fifths of the unicasts delivered, and the broadcasts gain the
airtime routes lose; there a full table of neighbours changes often,
and each neighbour found costs `ADDRESS_AFTER` addresses. Carrying the
address in every frame (96) cost more than that at SF7. Carrying it
while any neighbour gave no margin carried it almost always, since in a
crowd most nodes a node hears do not hear it back: 87.1% and 13.1% of
unicasts.

**Your address to your neighbours.** A signature is checked with the
signer's public key, and a Tern node's public key is its address. So a
node's neighbours, and anyone listening near it, learn its address,
which is what [first contact](first-contact.md) needs to reach it, and
which a node that has not turned [cards](cards.md) on otherwise keeps
to itself. A key of its own for routing would keep the address back,
but nothing would tie that key to the routing id, and a node could
then claim the id of any destination its neighbours had not heard
from. That a routing id is tied to the one address that makes it is
what lets a node trust a route to a destination it knows only by its
address, so the address is given up.

**What a signature does not stop.** A node with an address of its own
can still announce routes it does not have, at metrics it does not
have, and draw frames to drop them. [Forwarding](forwarding.md#hops)
already listens for each frame to be passed on, gives up neighbours
that do not, and takes another way, and only a message's destination
can [acknowledge](forwarding.md#messages) it; what else routing does
about such a node is [not yet specified](#not-yet-specified).

**Numbers that survive a restart.** A signature says who sent an
announce, not when. Before announces were signed, a node that started
again began its numbers anywhere, and its neighbours took an announce
that said it was starting whatever its number. A recorded one, sent
again later, would then make every neighbour drop every route through
its sender, as often as anyone cared to send it. With numbers that only
rise, a restart is a newer announce like any other, and a recorded one
is late. Storing a number ahead costs one write in `NUMBER_SAVE`
announces, and a node that stops without warning loses at most
`NUMBER_SAVE` numbers; one that restarts and stops again before an
announce goes on the air loses one, since until then it stores only one
ahead. Numbers are sixteen bits, so a recording comes to look newer
again once its sender has sent 32768 announces after it, or restarted
128 times having sent some: days at the least.

A neighbour forgotten (for its silence, for a nearer node, or for
frames lost) would otherwise come back with any announce of it that was
ever recorded, its routes and the margin it gave with it, and draw
frames to a node that is not there until they were lost enough times to
forget it again. Keeping its number costs six bytes, and
`FORGOTTEN_KEPT` is as many as the firmware's boards keep neighbours.

## What an observer learns

Announces are sent in clear. From them a listener learns:

* each nearby node's routing id, role, the power it sent at, and the
  neighbours it names, so the shape of the network around it;
* the routes relays list: which destinations they reach and how far;
* the address of each node that carries it, so which addresses are
  near it, and which routing id each has. Anyone who already knew an
  address could find its routing id before; now anyone near can learn
  the address from the id.

A routing id does not change, so a node can be followed by its
announces, as before: see [Not yet specified](#not-yet-specified).

## Not yet measured

* **Any of the parameters, on radios.** Each is the simulator's
  default, chosen over sweeps of a simulated channel.
* **Whether signal-to-noise ratio as the SX1262 reports it** tracks the
  floor well enough, frame to frame, for a 3 dB band.
* **Memory and time** for a table of `RELAY_PLACES` destinations on
  the nRF52840, whose 256 kilobytes `RELAY_PLACES` takes a quarter of.
* **`ADDRESS_AFTER` and `ADDRESS_EVERY`**, which were set and not swept.
* **The time to check a signature** on the boards Tern runs on, against
  how many announces a relay hears in a crowd. The firmware's own
  Ed25519 checks one in 2.6 ms on a desktop processor; a board is tens
  of times slower.
* **A leaf's busy share on radios**, against what the simulator gave.
* **Why a crowded network with small tables does not always settle.**
  With 32 or 64 places at SF7, six hours on, some seeds still sent
  requests and five times the announces of the others.

## Not yet specified

* **Closing the wait.** A starting node that knew which neighbours had
  heard it could select through those at once, and would never select
  through one that had not.
* **Nodes that lie.** A node with an address of its own can announce
  routes it does not have, or a destination's `seq` one newer than the
  destination gave, and starve every node that takes it until the
  destination is asked. A destination could sign each `seq` it takes,
  and a relay carry that signature with the route only when the `seq`
  changes; and a node could stop using a neighbour whose frames are not
  acknowledged.
* **Signed requests.** A request names no sender, and anyone may send
  one. The most it can do is make a node take a newer `seq`, or send a
  request on, within the requests' share of [the cap](#the-cap).
* **Two nodes with one routing id.** A node holds the address of the
  first it hears and discards the other's announces, so the second has
  no neighbour that holds the first; elsewhere either may be taken.
  This need not be an accident. A routing id is four bytes, so making
  keys until one has a chosen node's id takes about 2^32 tries, a day
  or so on one desktop processor. A node that holds the real address
  discards the copy, but one that does not yet hold it may take the
  copy's routes in the real node's name. The copy can then stop frames
  reaching that node; it cannot read or forge them, which their own
  encryption and signatures prevent. Eight-byte ids would put this out
  of reach and cost four more bytes in every id a frame carries; what
  that costs in delivery is not yet measured.
* **Rotating routing ids**, so that a node cannot be followed by its
  announces.
* **Who is a relay.** The simulator has nodes elect themselves from
  what they hear. Here it is configured.
* **Leaves that move**: finding a new relay, and moving the routes
  there.
* **The airtime budget** shared between nodes, of which this section's
  cap is one part.
* **Networks of more nodes than `RELAY_PLACES`**: routes kept within a
  region, and frames between regions by flooding or through nodes that
  join them.
* **A relay that has no route** for a frame taken by a default route
  saying so, so that the leaf stops trying it.
* **Which destinations a full table keeps.** It keeps the first it is
  told of, not those its node sends to.
