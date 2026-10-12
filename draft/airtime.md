# The airtime budget

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). The budget was
set before the simulator kept one. What was measured that sets its
numbers, and what keeping it then did to a mesh in the simulator, are
[below](#what-was-measured); the second is why the own part is now 2%
and the relayed part 7%, where this section first had 1% and 8%.
Every number here is
**provisional**, and the choices the maintainer is asked to make are
under [Not yet specified](#not-yet-specified).

Every node shares one channel ([Radio settings](phy.md#profiles)).
This section says how much of its time a node may spend sending, over
what span, how that is divided between routing, the frames it writes
and the frames it passes on for others, and what becomes of a frame
when its part has run out. It sits above the allowances that
[Routes](routing.md#the-cap) and
[Frames for every node](flooding.md#the-allowance) already keep, which
become parts of it, and below the region's limit on transmitting,
which it never exceeds.

Test vectors: [`vectors/airtime.json`](../vectors/airtime.json),
produced by [`vectors/tools/airtime.py`](../vectors/tools/airtime.py).

## Goals

1. **Every frame is paid for.** Whatever a node sends is charged to a
   part of its budget, on every profile, whether or not the region
   limits transmitting.
2. **What others ask is kept apart from what the user asks.** Frames a
   relay passes on cannot spend what its own frames need, and its own
   frames cannot spend what it gives others.
3. **Routing first.** A node whose frames have spent their parts still
   announces, so its neighbours still hear it and routes still form.
4. **Within the law.** A node that spends its budget at the rate it
   fills stays within its profile's limit, and the limit is checked as
   well.
5. **Said, not hidden.** A frame of the node's own that waits for the
   budget is shown as waiting for it, with an estimate of when it goes.

## Notation

As in [Frames that follow routes](forwarding.md): a **relay** forwards
other nodes' frames and a **leaf** does not, and the **airtime** of a
frame is its time on air under the profile in use
([Radio settings](phy.md#time-on-air)).

A **bucket** is a token bucket as [Routes' cap](routing.md#the-cap)
is: it fills at a share of the node's time, holds a window of that, or
the airtime of one 255-byte frame if that is more, and starts full. A
bucket **holds** a frame when what it has is at least the frame's
airtime. A frame **charged** to a bucket takes its airtime from it.

A node's **own** frames are those it writes, as Forwarding and Frames
for every node have it: a message, an acknowledgement or a
first-contact frame it is the source of, and a flood it begins. Every
other frame it sends it **passes on**.

## The parts

A node's budget is three parts:

| Part | Pays for | Fills at | Holds |
|---|---|---|---|
| **routing** | announces, requests, solicits and answers, its own and those it passes on | [Routes' cap](routing.md#the-cap) and, for a relay, its learning allowance | as Routes says |
| **own** | its own frames, but routing's | `BUDGET_OWN` | `BUDGET_OWN_WINDOW` |
| **relayed** | frames it passes on, but routing's | `BUDGET_RELAY` for a relay; a leaf has no relayed part | `BUDGET_RELAY_WINDOW` |

The routing part is Routes' cap and learning allowance, unchanged, and
nothing in this section adds to it or takes from it. The own and
relayed parts are each one bucket, kept as this section says. With the
values below, a relay's budget is 9.5% of its time, 9.6875% in its
first [`LEARN_FOR`](routing.md#the-cap), and a leaf's is 2.5%.

A node MAY fill either bucket at less than its share. It MUST NOT fill
one at more.

**The allowances inside.** The two buckets of
[Frames for every node](flooding.md#the-allowance) stay, inside the
parts: a flooded frame of the node's own is paid for by the bucket for
its own floods **and** by the own part, and one it passes on by the
bucket for those it passes on **and** by the relayed part.

**Which part pays.** By the frame's `hdr`:

| `hdr` | Frame | Its own | Passed on |
|---|---|---|---|
| `0x48`, `0x49` | a [message](forwarding.md#the-head) | own: waits | relayed: dropped |
| `0x50` | an [acknowledgement](forwarding.md#messages) | own: never held | relayed: never held |
| `0x51` to `0x54` | a [first-contact frame](first-contact.md#the-frame) | own: waits | relayed: dropped |
| `0x59` to `0x5C` | an [announce, request, solicit or answer](routing.md#announces) | routing | routing |
| `0x60`, `0x61`, `0x68` | a [flooded frame](flooding.md#the-head) | own and the flood bucket for its own: waits | relayed and the flood bucket for those passed on: dropped |

A first-contact frame that answers another, such as the responder's
`message_2`, is the node's own.

## Spending

A frame other than routing's is **paid for** when every
bucket that pays for it, by the table above, holds it. Then:

* **A frame of the node's own** is sent only once it is paid for. A
  node MUST NOT send it sooner. It waits until then; nothing in this
  section drops it.
* **A frame passed on** that is not paid for when it would be offered
  to the radio, after its random wait in
  [Forwarding](forwarding.md#sending) or
  [Frames for every node](flooding.md#passing-on), and after a
  [busy relay](flooding.md#a-busy-relay) has kept it, MUST be dropped.
  For a frame that follows a route, the node before hears nothing, and
  does as [Hops](forwarding.md#hops) says of a frame not passed on.
* **An acknowledgement** is never held or dropped for the budget. It is
  charged to its part, own or relayed, whatever that holds, and the
  bucket goes no lower than empty.

A frame sent is charged its airtime, when it is sent, to every bucket
that pays for it, all at once. A frame not sent is charged to none: one
that waits is charged when it goes, and one dropped, for the budget or
for any other reason, never.

Routing's frames are paid for as Routes says, and by nothing here.

**The region's limit as well.** Any frame, paid for or an
acknowledgement, is still sent only if the
[profile](phy.md#profiles) allows it. A node keeps the profile's
account as Radio settings says, beside its buckets, and is held to
whichever allows it later.

**Order.** The budget changes no order a node sends in. What
[Forwarding](forwarding.md#sending) says, acknowledgements first, then
frames passed on, then its own, stands, and so does sending a message
ahead of a position ([Positions](positions.md#when-a-position-is-sent)).
Since the parts are apart, a frame of one part waiting holds up no
frame of another.

A node that starts, or starts again, starts each bucket full.

## Profiles

Where a profile limits transmitting, the most a node's budget fills at
is no more than the limit: 9.6875% against 10% of any hour, on every
profile [Radio settings](phy.md#profiles) defines. That is not enough
on its own. A bucket starts full and holds a window's worth, so a node
can spend in one hour a little more than the rate the parts fill at,
and the profile's period has no start a bucket knows of. That is why
the profile's account is kept as well.

Where a profile does not limit transmitting, the budget is the only
bound on what a node sends.

A profile whose limit is less than 9.6875% of its period would need
parts of its own. None is defined, and such a profile MUST NOT be
added until its parts are: see [Not yet specified](#not-yet-specified).

## What a client is told

A message, a group message or an invite of the node's own that is
waiting, as the [companion protocol](companion.md#what-the-node-holds)
has it, waits for the budget when its first frame, or the frame it is
being tried again with, is not paid for. Its `reason` is:

* 1 if it has no route, and 2 if first contact is under way, as the
  companion protocol has them, whatever the budget holds;
* otherwise, of 3, the region's limit, and 4, the node's airtime
  budget, the one that lets it go later, and 3 if both let it go at
  once.

Reason 4 takes in the bucket for the node's own floods, as it did
before this section: a group message waits for that bucket and the own
part together.

Its `wait`, for reason 4, SHOULD be how long until it goes if nothing
else is charged to its buckets meanwhile: the frames of the node's own
waiting go in order, each when every bucket that pays for it holds its
airtime and not before the frame ahead of it, and each is charged to
its buckets as it goes. In seconds, rounded up, and at most `0xFFFF`.
For reason 3, as Radio settings gives it, the same way rounded. A frame
held up by a bucket it does not pay from, such as a message behind a
group message waiting for the flood bucket, waits as long as the frame
ahead of it.

## Parameters

| Name | Value | |
|---|---|---|
| `BUDGET_OWN` | 2% | of a node's time |
| `BUDGET_OWN_WINDOW` | 600 s | as `FLOOD_OWN_WINDOW` |
| `BUDGET_RELAY` | 7% | of a relay's time |
| `BUDGET_RELAY_WINDOW` | 60 s | as `FLOOD_RELAY_WINDOW` and `CAP_WINDOW` |

## Conformance

An implementation conforms to this section if, for
[`vectors/airtime.json`](../vectors/airtime.json):

* **parts:** as a node of the `role` given, it fills its own part at
  no more than `own_ppm` millionths of its time and holds
  `own_window_s` seconds of that, and its relayed part likewise at
  `relayed_ppm` and `relayed_window_s`, or keeps none where they are
  `null`;
* **classes:** it pays for a frame with `hdr`, its own or passed on as
  `own` says, from `part` and from the flood bucket
  `flood_allowance` names, if any; and a frame they do not all hold
  waits, is dropped, or is sent and charged with the bucket going no
  lower than empty, as `unpaid` says;
* **spends:** as a node of the `role` given, on the `profile` given,
  filling each bucket at its full share, every bucket full at time 0,
  offered each frame of `frames` in order, the node's own or passed on
  as `own` says, of `airtime_ns` at `at_ns`, it sends the frame then,
  or not, as `sent` says. A frame sent is charged to every bucket that
  pays for it, and one not sent to none;
* **estimates:** having spent the frames of `spent` as in **spends**,
  with its own frames of `waiting` waiting in that order at `at_ns`, it
  finds each frame's `wait_s`;
* **reasons:** for a message of its own waiting with a route or not,
  and a session or not, as `route` and `session` say, that the region's
  limit would let go in `region_wait_s` seconds and the budget in
  `budget_wait_s`, it gives `reason` and `wait`.

That a mesh of nodes keeping budgets delivers what it should is checked
by running implementations against each other and against the
simulator.

## What an observer learns

Nothing on the air changes: no frame carries a budget. A relay whose
relayed part is spent drops frames it would have passed on, and goes on
announcing; an observer who hears frames sent to it and not passed on,
while its announces go on, may take its part to be spent, as it may
take a [busy relay](flooding.md#a-busy-relay) to be busy. A node's
own frames held for its budget go later, and say no more about how
much it writes than the frames themselves did.

## Rationale

**What the budget is for.** It bounds what any one node can take from
the channel: its user, its software, or anyone who hands it frames to
pass on. It does not keep a mesh within what the channel holds. Shares
of each node's time add up past the channel: a thousand nodes, each
allowed 0.5% for their own floods, are together allowed five channels
([Frames for every node](flooding.md#what-was-measured)). What sees
the channel as a whole is a node's own radio, which is what a
[busy relay](flooding.md#a-busy-relay) acts on.

**Parts, not one bucket.** One bucket for everything, with priorities
inside it, was the other shape. In one bucket the frames others ask a
relay to pass on spend what its user's need, and a user who writes a
great deal spends what the relay owes others. Reserving some of one
bucket for one kind of frame, as
[Positions](positions.md#when-a-position-is-sent) reserves a frame of
the own flood bucket for words, answers one direction at a time and
needs a threshold for each. Parts carry the reason Frames for every
node keeps its two buckets apart, that a relay spent on others' floods
can still send its own, to every kind of frame. What parts cost: a
part unused is not lent to another, so a relay with nothing to pass on
cannot spend its relayed part on its own frames. That is on purpose.
The own part is what bounds one user, and it bounds them the same
whether their node is a relay or a leaf.

**Above the allowances, not in place of them.** Routes' cap is the
routing part as it is. The flood buckets stay inside the own and
relayed parts, so floods cannot take all of either: within the own
part, a group can take a quarter and messages the rest; within the
relayed part, floods passed on 3% of a relay's 7%. Replacing them with the
parts would have changed what was measured of floods for no gain.

**Token buckets, not a sliding period.** Routes' cap and the flood
allowances are token buckets, and the budget is one more of the same:
a few numbers to keep, a rule the vectors already test, and a burst
that a conversation's few messages can go in at once. A sliding period
is what a regulator writes, and the profile's account keeps one; it
needs a record of past frames, which the firmware keeps as 61 slices
(ternmesh/firmware, `tern/duty.h`). A budget that kept the profile's
own period would also say nothing on the profiles that have none,
which are most of them.

**Routing outside the parts for frames.** Goal 3. Announces already
have their own bucket. If they shared one with the frames a relay
carries, a relay busy carrying frames would fall silent, and its
neighbours would lose the routes through it just when they were most
used. A neighbour heard is also what keeps a node from
[forgetting it](forwarding.md#hops) when its frames go unanswered.

**A relay gets more than a leaf.** Relays carry everything. On the fast
preset, across every candidate, the busiest node sent 1.4 to 8.2% of
the hour, candidate 3's and MeshCore's the most where the network is
sparsest, their relays carrying all of it; at the slow preset, under
4%. Held to 1% of the hour, every candidate collapsed
([What was measured](#what-was-measured)). A leaf passes nothing on,
so a relayed part would be air it could never spend.

**7% for a relay.** It is what is left of the 10% that three profiles
allow once routing, at its largest, and the own part are taken out,
rounded down: 9.6875% in all. It is below the most any node was
measured sending in a whole hour, which counts every frame that node
sent, its own and routing included. Over a minute it binds a little,
and only where relays are busiest: the ten busiest relays measured
dropped 0.5 to 5.8% of what they were asked to pass on, and delivery
did not move ([What the budget did](#what-the-budget-did)). It began
to cost at 4%. It was 8% until the own part took a point of it; at 8%
the busiest relay dropped 5.3%, and delivery did not move either.

**2% for a node's own.** The simulator's workloads send a message from
each node every half hour, or in the heaviest flooding run every five
minutes. One try of a 67-byte message frame on `EU868` takes
131.328 ms, so a message every five minutes, tried once, is 0.044% of
a node's time; 2% is more than forty times that. It binds a node that
writes far more than any workload measured: a bot, a client in a loop,
or a user who writes without pause. Ten minutes of it is 12 s of
airtime, ninety-one such frames at once. It is 2%, not the 1% this
section first had, for retries: a message may go from its source 24
times, four tries of three sends each and once more
[another way](forwarding.md#hops), and where frames are lost it does.
24 sends of a 60-byte frame take 2.9 s on `EU868`'s modulation and
9.7 s at SF9; at 1%, 6 s, one or two messages' retries spent the part,
and in a full network every node is retrying. Measured, 1% held a
node's frames for minutes there and made a full network worse; 2% held
a tenth as many, and at six times the traffic cost about a point of
unicasts on time where 1% cost three quarters or more of them
([What the budget did](#what-the-budget-did)). What 2% gives up is some
of the shield: against nodes that write without pause, the rest of the
mesh delivered 1.5 to 2.9 times as many unicasts on time as with no
budget, where 1% did better still.

**Windows.** The own part holds ten minutes, as the own flood bucket
does: a person writes in bursts, a few messages and then none. The
relayed part holds a minute, as Routes' cap and the flood relay bucket
do, so that the most others can ask of a relay at once is 4.2 s of
airtime, ten 255-byte frames on `EU868` and thirteen on `US915`.

**A frame passed on is dropped, not held.** The node before listens
for it for [`HOP_WAIT`](forwarding.md#hops) and twice its airtime,
then sends it again. Held longer than that, the frame goes twice.
Dropped, it is sent again, and then
[another way](forwarding.md#hops) if there is one: the load moves off
a relay that has spent its part. Since that relay still announces, its
neighbours do not forget it for the frames it dropped.

**A node's own frame waits.** The user asked for it, and a client can
say why it waits and for how long. Dropping it would leave the user to
send it again, which spends the same.

**An acknowledgement is never held.** It ends a message whose every
hop has been paid for already; held, its source sends the message
again over the whole path. It is charged so that it counts, but the
bucket goes no lower than empty: copies of a message sent to a node
again and again would otherwise run its own part into a debt that held
its user's frames long after the copies stopped. A node made to send
acknowledgements so is sent at least as much: a copy is 23 bytes or
more, an acknowledgement 19.

**Neighbours do not learn each other's load.** A byte in each announce
with the share a relay has left, and routes that avoided relays with
little, was considered. It costs a byte in every announce, which is the
routing part's own spend, and a metric that moves with load moves
routes, which costs announces again: in the simulator's town, an
allowance spent on any changed route went on being spent
([Routes](routing.md#rationale)). A spent relay already sheds its load,
by dropping and so being tried another way. In the simulator that was
enough: a unicast that lost a frame to a spent relay arrived on time
as often as any other, and relays spent their part rarely
([What the budget did](#what-the-budget-did)).

**What the client is told.** Reason 4 was named in the companion
protocol before the budget was written, and was already used for the
own flood bucket. A message held by both the region's limit and the
budget is shown with the one that clears later, since that is when it
goes; the region's, where both clear at once, since no setting changes
it.

## What was measured

First, before any simulator kept the budget, the figures its numbers
rest on, each recorded where it was measured:

* **The busiest node.** On the fast preset, SF7 at 125 kHz, a thousand
  nodes and 200 relays, the busiest node of any candidate sent 1.4 to
  8.2% of the hour from −5 to 20 dBm, the most where the network is
  sparsest (ternmesh/sim, `scenarios/scale/region-distvec-fast.tsim`).
  On the slow preset, under 4% (`region-distvec-deployed.tsim`).
* **A smaller limit.** With every radio held to 1% of the hour, every
  candidate collapsed, candidate 3 to 1.0% and 2.2% of unicast
  messages on time at 0 and 20 dBm, against nothing changed at 10%
  (`region-distvec-deployed.tsim`, MSH-65).
* **Routing's share.** An announce cap of 2% saturated a 200-node town
  at SF9, where 0.5% did not (`include/tsim/distvec.h`). Once settled,
  the busiest node of that town spent 0.42 to 0.64% of its time on
  routing ([Routes](routing.md#rationale)).
* **The flood allowances.** At the traffic of the fast preset's runs
  they do nothing; at a message from every node every five minutes,
  only the relays' binds, and only where relays are few
  ([Frames for every node](flooding.md#what-was-measured)).

Those runs are SF7 at 125 kHz, the modulation of `EU868`, `RU868` and
`KZ863`. A frame on the 500 kHz profiles at SF9 takes no longer: a
255-byte frame is 320.768 ms there against 407.808 ms, so a share of
time buys at least as many frames.

### What the budget did

ternmesh/sim kept the budget for candidate 3's frames, as
`vectors/airtime.json` had it with the values this section first had,
own 1% and relayed 8%, on the 200-node town at SF9 and on the
thousand-node region's fast preset (SF7 at 125 kHz) and deployed
preset (SF8 at 62.5 kHz, coding rate 4/8), at -5, 0 and 20 dBm, beside
Meshtastic and MeshCore, which keep none
([ternmesh/sim, `docs/airtime.md`](https://github.com/ternmesh/sim/blob/main/docs/airtime.md),
MSH-92). At the comparison's traffic, a message from every node every
half hour:

* **The relayed part**, at 8%, dropped nothing on the fast preset or in
  the town, where the busiest relay passed frames on for 0.7 to 2.2% of
  its hour. On the deployed preset it dropped 0.07 to 1.2% of what relays
  were asked to pass on, 0.4 to 3.6% at the ten busiest, 5.3% at the
  busiest, and unicast on time moved by under a point; the busiest node
  there, with no budget, sent for 3.7 to 6.9% of its hour, more than
  the figure above. At 4% the ten busiest dropped up to 21% and unicast
  fell 2.6 points; at 2%, 3 to 10 points. At 12% it dropped next to
  nothing.
* **The own part**, at 1%, held nothing on the fast preset and 5 frames
  an hour in the town. On the deployed preset it held frames 3,100 to 4,600
  times an hour, about a minute at a time: unicast on time did not
  move, the 95th-percentile delay doubled or more, to 151 to 291 s,
  past the 60 s deadline, and deliveries per second of airtime rose 12
  to 47%, the retries held back having been mostly lost anyway. At 2%
  it held a tenth as many, for under half a minute, and delay was as
  with no budget.

At six times that traffic, a message every five minutes, the town fell
from 19.9% of unicasts on time to 4.9% with the own part at 1%, which
held frames some 19,000 times an hour, and to 18.7% at 2%; at 4% nothing
was held. The deployed preset fell from 2.1-3.7% to 0.2-0.7% at 1%, and to
1.8-3.0% at 2%. The fast preset, whose frames are a third as long,
held almost nothing at 1%; there, at -5 dBm, the relayed part at 8%
dropped 10% of what the busiest relay was asked, the ten busiest 2.3%,
with delivery unchanged.

Own 2% and relayed 7%, the values adopted, which keep a relay's budget
at 9.6875% of its time, delivered on the deployed preset 23.1, 24.2 and
12.3% of unicasts on time at -5, 0 and 20 dBm, against 22.6, 22.7 and
11.5% with own 1% and relayed 8% and 22.5, 23.4 and 11.9% with no
budget, with delay as with no budget. The ten busiest relays dropped
5.8, 2.8 and 0.5% of what they were asked to pass on.

With a twentieth of the nodes writing a message every 10 seconds, the
own part did what it is for: the other nodes' unicasts arrived on time
36 to 69% of the time on the fast preset against 14 to 19% with no
budget, and 11 to 18% against 3 to 10% on the deployed preset; at 2%,
25 to 52% and 10 to 17%. The writers sent only stale messages: their
own part let their frames go slower than they came, nothing drops a
frame of a node's own, and every message went out behind a backlog
minutes long.

## Not yet measured

* **The windows**: neither `BUDGET_OWN_WINDOW` nor
  `BUDGET_RELAY_WINDOW` was varied in the simulator.
* **The 500 kHz profiles**: every run was at 125 kHz or 62.5 kHz, where
  a frame takes longer and the own part binds sooner.
* **The own part against what people send**, from a workload drawn
  from the field rather than one message every half hour.
* **Any of it through the firmware's own code, or on radios.** The
  simulator could not run its budget over the firmware's core: the
  forwarder there has no way to drop a frame it was given to pass on.

## Not yet specified

Each of these is a choice for the maintainer.

* **What is left, for a client.** `AIRTIME` gives only the region's
  limit. A later version of the companion protocol could add fields
  at its end, as that protocol allows: what the own part holds when
  full and now, in milliseconds, and how many milliseconds until it
  holds a 255-byte frame. That is what a screen showing "what is left"
  needs, and is left out here until the parts are agreed.
* **How long a frame of the node's own may wait.** Nothing drops one,
  so a node writing faster than its own part fills sends every message
  behind its backlog, late. A limit on how many may wait, or for how
  long, would go with the companion protocol's reason 4.
* **Withdrawing a frame that waits.** A client cannot take back a
  message waiting for the budget, though it can a group message by
  leaving the group.
* **Words first in the own part.** Positions keep a frame of the own
  flood bucket for words. Whether a position should also leave a
  frame of the own part is not said.
* **Profiles with a smaller limit.** India, Singapore, Vietnam and
  Indonesia limit transmitting by role, to 1% or 2.5% for a node that
  is not an access point ([Radio settings](phy.md#not-yet-specified)).
  Parts for those need measuring, not scaling.
* **Neighbours' load**, [above](#rationale): whether a relay should
  say how much it has left, and whether routes should heed it.
* **A node's own choice.** A node may fill a part at less than its
  share, but nothing says how its user chooses that, or whether a relay
  on a mains supply and a good mast should ever get more.
* **Sleeping leaves**, whose budget would fill while they sleep.
