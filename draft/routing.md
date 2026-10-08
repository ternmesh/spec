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
unsigned and `i8` is a signed byte.

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
| 9 | 1 | `flags` | bit 0: the sender is a relay. Bit 1: it is [starting](#starting). The rest are 0 |
| 10 | 2 | `promise` | the longest the sender may go before its next |
| 12 | 2 | `round` | announces it takes the sender to name every neighbour |
| 14 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |
| 15 | 1 | `h` | how many neighbours follow |
| 16 | 1 | `r` | how many routes follow |
| 17 | 5`h` | neighbours | each `id` `u32`, `margin` `u8` |
| 17 + 5`h` | 8`r` | routes | each `destination` `u32`, `seq` `u16`, `metric` `u16` |

`hdr` has format `01` (draft 0), type `011` (routing) and flags `001`
(announce). The frame is exactly `17 + 5h + 8r` bytes, and at most 255.
A receiver MUST discard one of any other length, one whose `sender` is
its own id or a reserved id, and one whose `flags` has an unknown bit
set.

**`number`** starts at a random value and goes up by one with each
announce sent.

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
the last from the same sender is a copy or is late, and is discarded
whole, unless it says its sender is [starting](#starting), or nothing
has been heard from that sender for one of its promises. In that last
case the sender started again unheard: the node forgets it, and every
route through it, and takes the frame as from a neighbour it has just
found.

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

A node that hears a neighbour say it is starting, when that neighbour's
last announce did not, forgets the neighbour and every route through
it, and takes the frame as from a neighbour it has just found. It MUST
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
| `LINK_COST` | 70 ms on `US915`, 81 ms on `EU868` | |
| `ROUTES_KEPT` | 4 | for each destination |
| `HYSTERESIS` | 1/10 | |
| `CHANGE` | 1/4 | |
| `RETRACTS` | 3 | |
| `START_ANNOUNCES` | 4 | announces a node is starting for |
| `REQUEST_INTERVAL` | 10 s | |
| `REQUEST_TRIES` | 5 | |
| `HOP_MAX` | 32 | |
| `JITTER` | 2 | airtimes |

## Conformance

An implementation conforms to this section if, for
[`vectors/routing.json`](../vectors/routing.json):

* **ids:** given `address`, it derives `id`;
* **newer:** it finds `a` newer than `b`, or not, as `newer` says;
* **promises:** it encodes `seconds` as `code`, and reads `code` as
  `read_seconds` (`null` for no promise);
* **announces** and **requests:** it builds `frame` from the fields
  given, and reads the fields from `frame`;
* **rejected:** it discards each `frame`;
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
  `promise_passed` says whether nothing was heard from the neighbour
  for one of its promises, `starting` whether the announce says so, and
  `was_starting` whether the neighbour's last did;
* **costs:** for each profile, a link costs `link_cost`;
* **feasible:** with the feasibility distance given (`null` for none),
  it finds each route feasible or not;
* **selection:** with the routes given, each through a neighbour it may
  use, and `selected` naming the one selected before (`null` for none),
  it selects `selects`;
* **kept:** with four routes held and `selected` among them, offered
  `offered`, it replaces `replaces` (`null` for none).

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
and a frame holds 29. With the 32-byte address it would hold six. A
hash of the address rather than its first bytes, so that the id gives
away nothing of an address an observer does not already have. Two
nodes in four billion pairs share one; see below.

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

## Not yet measured

* **Any of the parameters, on radios.** Each is the simulator's
  default, chosen over sweeps of a simulated channel.
* **Whether signal-to-noise ratio as the SX1262 reports it** tracks the
  floor well enough, frame to frame, for a 3 dB band.
* **Memory and time** for a table of a thousand destinations on the
  nRF52840.
* **Why a crowded network with small tables does not always settle.**
  With 32 or 64 places at SF7, six hours on, some seeds still sent
  requests and five times the announces of the others.

## Not yet specified

* **Closing the wait.** A starting node that knew which neighbours had
  heard it could select through those at once, and would never select
  through one that had not.
* **Authentication.** Nothing here is signed. A node can announce a
  route it does not have, claim another's routing id, or raise
  another's sequence number. A signature is 64 bytes, a quarter of a
  frame.
* **Two nodes with one routing id.**
* **Rotating routing ids**, so that a node cannot be followed by its
  announces.
* **Who is a relay.** The simulator has nodes elect themselves from
  what they hear. Here it is configured.
* **Leaves that move**: finding a new relay, and moving the routes
  there.
* **The airtime budget** shared between nodes, of which this section's
  cap is one part.
