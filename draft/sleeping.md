# Leaves that sleep

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Unlike the
sections on routes and forwarding, it was **not** measured in the
simulator before it was written: what needs measuring is under [Not yet
measured](#not-yet-measured). Every number here is **provisional**.

A [leaf](routing.md#roles) passes nothing on, so nothing but its own
frames needs it on the air. Yet a leaf as [Routes](routing.md) has it
listens all the time, because a frame for it may come at any moment,
and a LoRa radio listening draws thousands of times what it draws
asleep. This section lets a leaf turn its radio off between short,
regular wakes, and still receive what is sent to it: a relay it chooses,
its **keeper**, holds the leaf's frames while it sleeps and hands them
over when it wakes.

The leaf wakes on its own clock and asks; nothing is sent to a leaf
that has not just asked. So no node keeps time with another, no frame
needs a longer preamble to catch a leaf as it wakes, and a leaf's
neighbours spend nothing to keep it reachable.

Test vectors: [`vectors/sleeping.json`](../vectors/sleeping.json),
produced by [`vectors/tools/sleeping.py`](../vectors/tools/sleeping.py).

## Goals

1. **Asleep nearly all the time.** A leaf that sleeps is on the air
   only to send its own frames and for a short listen after each, and
   a frame for it costs it nothing until it wakes.
2. **What is sent to it arrives.** A message for a sleeping leaf is
   held, not lost, and its source waits for it rather than giving it up.
3. **Nothing kept in step.** No node needs to know when another will
   wake. The leaf says how long it may sleep, and asks when it wakes.
4. **Bounded at the keeper.** What a relay holds for leaves is bounded
   by frames and by time, and holding costs its neighbours nothing.
5. **The rest of the mesh unchanged.** Routes to a sleeping leaf are
   routes to a leaf, through its keeper. A node that is not its keeper
   needs to know only not to send to it directly.

## Notation

As in [Routes](routing.md#notation) and
[Frames that follow routes](forwarding.md#notation). `airtime(L)` is the
time on air of a frame of `L` bytes on the node's profile. The values
this section names in `CAPITALS` are in [Parameters](#parameters).

A wake time `w` is given in the encoding of an announce's
[`promise`](routing.md#announces): seconds up to 32767; with the top bit
set, the low 15 bits are minutes. `0xFFFF` is not a wake time.

## Sleeping

A leaf **sleeps** when its last announce had bit 3 of `flags` set
([Announces](#the-announce)). While it sleeps it chooses for itself
when to listen, and its radio is off the rest of the time. A relay
MUST NOT sleep.

A leaf MUST NOT sleep while it is [starting](routing.md#starting), nor
while it has no **keeper**: a relay neighbour whose link is
[up](routing.md#links) and which it may [use](routing.md#roles). Its
keeper when it begins to sleep is its [anchor](routing.md#leaves-that-move).
It keeps that keeper until it [changes it](#changing-keeper).

A sleeping leaf has a **wake** `w`, from `WAKE_MIN` to `WAKE_MAX`: the
longest it lets pass between one [poll](#polls) and the next. It has
a **listen** `l`, in whole seconds from `LISTEN_MIN` to 255: how long
it listens after each poll, and after every frame it sends.

**Awake.** A sleeping leaf MUST listen from each frame it sends until
`l` seconds after it went on the air, and MAY listen at any other time.
So a frame of its own, whose hop it listens for, and the
acknowledgement of a message of its own, which its keeper hands on in
that time, both find it awake. A leaf whose own message waits for an
acknowledgement longer than `l` SHOULD poll again before `l` runs out,
to keep listening.

**Its own frames.** A sleeping leaf sends every frame of its own to its
keeper, whatever routes it holds, as by its [default
route](routing.md#a-leafs-default-route). It hears too few announces
asleep to keep routes of its own.

**Floods.** A sleeping leaf receives a [flood](flooding.md) only if it
hears one while it listens. Nothing holds floods for it: see [Not yet
specified](#not-yet-specified).

**Stopping.** A leaf stops sleeping by announcing with bit 3 clear. It
then listens all the time, as any leaf does.

## The announce

An announce whose sender sleeps says so, and names the keeper:

* bit 3 of `flags` is **sleeps**. A relay MUST NOT set it. A receiver
  MUST discard an announce from a relay with it set;
* with bit 3 set, the 4-byte routing id of the sender's keeper,
  `keeper`, follows `r`, at offset 17, before the key if the key is
  carried.

So the frame is `81 + 4s + 32a + 5h + 8r` bytes, `s` being 1 if bit 3
of `flags` is set and 0 otherwise. Everything else is as
[Routes](routing.md#announces) has it, and `keeper` is signed with the
rest. A receiver MUST discard one whose `keeper` is a reserved id.

**When a sleeping leaf announces.** Not by Trickle: a sleeping leaf
announces just before a poll, once at least every `SLEEP_ANNOUNCE`, and
also before the first poll after it changes its keeper or its `seq`.
Its `promise` is at least what is left until the poll after its next
announce is due, plus `l`. A sleeping leaf names first, among its
neighbours, its keeper. It carries its key as Routes requires, counting
the announces it sends.

**Using a sleeping leaf.** A node MUST NOT use a neighbour that sleeps,
by its last announce taken, as the next hop for any frame unless it is
that neighbour's keeper. Other nodes reach it by the route its keeper
announces, which is a route to a leaf like any other.

## Polls

A sleeping leaf wakes and asks its keeper for what it holds:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | `0x5D` |
| 1 | 4 | `sender` | the leaf's routing id |
| 5 | 4 | `keeper` | its keeper's routing id |
| 9 | 2 | `id` | counts the leaf's polls, from a random value |
| 11 | 2 | `wake` | `w` |
| 13 | 1 | `listen` | `l`, in seconds |
| 14 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |

A **poll**. `hdr` has format `01`, type `011` (routing) and flags `101`
(poll). The frame is exactly 15 bytes.

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | `0x5E` |
| 1 | 4 | `sender` | the keeper's routing id |
| 5 | 4 | `leaf` | the routing id of the leaf it answers |
| 9 | 2 | `id` | the poll's |
| 11 | 1 | `margin` | the margin the keeper gives the leaf, as in an announce |
| 12 | 1 | `held` | how many frames it holds for the leaf, at most 255 |
| 13 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |

A **poll answer**. `hdr` has type `011` and flags `110`. The frame is
exactly 14 bytes. A receiver MUST discard a poll or a poll answer of
any other length, one whose `sender` is its own id or a reserved id,
a poll whose `keeper`, and a poll answer whose `leaf`, is a reserved
id, and a poll whose `wake` is `0xFFFF`, under `WAKE_MIN` or over
`WAKE_MAX`, or whose `listen` is under `LISTEN_MIN`. Neither is signed:
see [Not yet specified](#not-yet-specified).

**Polling.** A sleeping leaf MUST send a poll within `w` of its last,
by the `w` that poll gave, and sends it at the power of a frame for its
keeper ([Power](routing.md#power-for-every-neighbour)). It gives its
first poll a random `id`, and each after it one more. It MAY poll
sooner: when it has a frame of its own to send, to keep listening, or
because the last answer said frames were still held.

**What a poll tells.** A node that hears a poll or a poll answer from a
neighbour it keeps takes its `power` and signal-to-noise ratio as a
sample for the neighbour's floor, as from an announce, and as a sign of
life. A leaf that hears a poll answer for itself from its keeper takes
`margin` as the margin its keeper gave, as from a
[solicit's answer](routing.md#leaves-that-move). One from a node it does
not keep, it takes nothing from.

A relay takes a leaf's keeper as named in the leaf's last poll or
announce it took, whichever came later.

**Answering.** A keeper that hears a poll naming it from a neighbour it
keeps MUST answer it once, by `sender` and `id`, after a random time up
to `JITTER` × `airtime(14)`, at the power of a frame for that neighbour,
with `held` the number of frames it [holds](#holding) for it. The
requests' bucket of [the cap](routing.md#the-cap) pays for the answer;
one it cannot pay for is not sent, and the leaf asks again.

**What the leaf does.** A leaf that hears the answer to its poll
listens until it has received `held` frames from its keeper, or until
its listen ends, whichever is first. A leaf whose listen ended with
frames still held MAY poll again at once.

## Holding

A keeper takes its leaf as **awake** from when it receives any frame
from it until `l` seconds have passed since then, by the `l` of the
leaf's last poll: awake while less than `l` has passed, and asleep from
`l` on.

**What is held.** A keeper that has a frame to send to its sleeping
leaf as the next hop, while the leaf is not awake, MUST NOT send it. It
**holds** it, and answers the node it came from at once, as below. A
frame whose hop to the leaf is given up while it was awake is held
then, the once: it is not sent another way. A keeper MUST hold, for
each sleeping leaf it keeps, at least `HOLD_LEAF` frames, and MAY hold
more; a frame for which it has no room is dropped, unanswered.

A frame held is not finished with ([Receiving](forwarding.md#receiving)):
a copy that arrives is not held again, and is answered as the first was.

**The held notice.** A keeper that holds a frame, or a copy of one it
holds, sends the node it came from, once and not listened for:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | `0x55` |
| 1 | 1 | `hops` | 0 |
| 2 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |
| 3 | 4 | `next` | the routing id of the node the frame came from |
| 7 | 4 | `destination` | the frame's |
| 11 | 4 | `tag` | the frame's |

It is a frame of [Frames that follow routes](forwarding.md#the-head),
exactly 15 bytes, sent at the power the node before needs, as any frame
sent in answer to one received. To the node it is for, it ends the hop
of a frame with that `destination` and `tag` sent to the keeper, as
hearing the frame passed on would ([Hops](forwarding.md#hops)), and it
teaches nothing: as of an acknowledgement, no node takes a sample from
it or anything off a boost. Only the leaf's keeper sends one; no node
passes one on.

**Handing over.** Once it has answered a poll, a keeper sends the
frames it holds for the leaf, while the leaf is awake: acknowledgements
first, then the rest, each in the order it arrived. Each goes as any
frame to a neighbour does, as a hop with its retries. A frame is
finished with once its hop has succeeded; for a message, that is when
the keeper passes on the leaf's acknowledgement of it. An
acknowledgement or a first-contact frame for the leaf, whose last hop
is not listened for, is finished with once sent. A frame whose hop is
given up stays held. A frame that the [relayed
part](airtime.md#the-parts) does not pay for when it would be sent
stays held, and is not dropped for the budget.

**How long.** A keeper MUST drop a frame it has held for longer than
`HOLD_FOR`, reckoned from when it was first held:

```
HOLD_FOR = 2 × w + HOLD_EXTRA
```

with `w` from the leaf's last poll, or its last announce's `promise` if
it has not polled.

**A leaf that names another keeper.** A relay holding frames for a leaf
whose last poll or announce now names another keeper, or which has
[gone out of use](routing.md#leaves-that-move) to it, MUST stop holding
them: it passes each on by its route, as a frame it receives, without
taking `hops` down again. A relay that forgets the leaf drops them.

## Changing keeper

A leaf whose `POLL_TRIES` polls in a row have had no answer from its
keeper takes the keeper [out of use](routing.md#leaves-that-move), and
does as a leaf that solicits does on finding it has moved. A poll that
had no answer is followed by the next after `POLL_RETRY`, not after
`w`, and the leaf need not listen between them but for `l` after each.

When it has an anchor again among the relays it may use, the leaf
**re-attaches** as Routes says: its `seq` goes up by one, and it takes
that anchor as its keeper, naming it in its next announce and its next
poll. The newer `seq` draws every route to it through the new keeper,
and the old one, hearing of it, passes on what it held
([above](#holding)).

A leaf MAY also change keeper when its keeper's link goes down, or for
another relay whose link has `KEEPER_BAND` more margin, in the same
way.

## Telling the source

A source that does not know its destination sleeps gives a held message
up after its four tries ([Messages](forwarding.md#messages)), though
the keeper still holds it and the leaf may still receive it: the
acknowledgement then comes too late, and the source ignores it. So a
sleeping leaf tells those it has sessions with how long they should
wait, end to end, in a frame for the node
([`node`](unicast-security.md#the-frame) set):

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x04`: sleep |
| 1 | 2 | `wake` | `w`, or 0 for not sleeping |

It is exactly 3 bytes; a receiver MUST ignore one of any other length,
or with `wake` `0xFFFF`, or not 0 but under `WAKE_MIN` or over
`WAKE_MAX`.

A sleeping leaf SHOULD send one to each node it holds a session with
when it begins to sleep, when its `w` grows, and when it stops
sleeping, and MAY send one at any other time. The last a node accepts
in a session is what it holds for that session's other end.

**Waiting longer.** A source that holds a `w` other than 0 for a
message's destination waits, for each of its tries,

```
ACK_WAIT + ACK_FACTOR × the route's metric + 1000 × w + 1000 × LISTEN_MIN, in milliseconds
```

in place of [Messages](forwarding.md#messages)' wait, `w` being in
seconds.

**Copies.** A sleeping leaf acknowledges a copy for `COPY_TIME` plus
`RETRIES + 1` times its `w`, not `COPY_TIME` alone: the source's later
tries come that much later.

## Paid for

| `hdr` | Frame | Pays |
|---|---|---|
| `0x5D`, `0x5E` | a poll or a poll answer | routing: the requests' bucket of [the cap](routing.md#the-cap) |
| `0x55` | a held notice | own, as an acknowledgement is: never held |

A frame a keeper hands over is passed on, and paid for by the relayed
part when it goes; until then it is charged to nothing.

**A leaf's buckets while it sleeps.** A bucket fills while its node
sleeps as at any other time, and never holds more than its window. So a
leaf that wakes after a long sleep has a full budget, and no more:
nothing here changes [the airtime budget](airtime.md).

## Parameters

| Name | Value | |
|---|---|---|
| `WAKE_MIN` | 30 s | the shortest wake |
| `WAKE_MAX` | 3600 s | the longest wake |
| `LISTEN_MIN` | 2 s | the shortest listen |
| `HOLD_LEAF` | 8 | frames a keeper holds for each leaf, at least |
| `HOLD_EXTRA` | 60 s | |
| `SLEEP_ANNOUNCE` | 3600 s | the longest between a sleeping leaf's announces |
| `POLL_TRIES` | 3 | polls in a row unanswered before a leaf changes keeper |
| `POLL_RETRY` | 10 s | after a poll unanswered |
| `KEEPER_BAND` | 6 dB | |
| `JITTER` | 2 | airtimes, as in Routes |

## Conformance

An implementation conforms to this section if, for
[`vectors/sleeping.json`](../vectors/sleeping.json):

* **polls**, **poll_answers** and **held_notices:** given the fields,
  it produces exactly `frame`; and, as the node `other` of
  `routing_ids`, it reads them back from it;
* **rejected:** as `other`, it discards each `frame`;
* **announces:** given `seed` and the fields, as [Routes'
  vectors](../vectors/routing.json) do, with `sleeps` and `keeper`, it
  produces exactly `frame`; and as `other`, holding no key for the
  sender, it takes it, or discards it, as `taken` says;
* **sleep:** given `wake`, it produces exactly `content`; and it
  accepts, or ignores, each `content` as `valid` says;
* **holds:** as a keeper, `at_ms` milliseconds after it received its
  leaf's last frame, the leaf's last poll having given `listen`, it
  holds a frame for the leaf, or sends it, as `holds` says;
* **hold_for:** given `wake`, it drops a frame held `hold_for` seconds;
* **source_waits:** given `metric` and `wake`, a source waits `wait_ms`
  for each try.

## What an observer learns

A sleeping leaf's announces say that it sleeps and name its keeper, and
its polls say how long it sleeps and how long it listens, all in the
clear, beside the routing id its announces already carry. So anyone in
earshot of a sleeping leaf learns, for as long as its routing id stays
the same, when it is on the air and which relay holds its frames, as
they can already learn its neighbours. Its keeper learns how many
frames are sent to it, and when, but not from whom or what they say,
which their own encryption hides.

The `kind` `0x04` frame is end to end, and tells only those the leaf
holds sessions with how long it sleeps.

## Rationale

**Why sleeping leaves at all.** A LoRa radio listening draws about
4.6 mA (SX1262, 125 kHz, datasheet) and asleep about 1 µA, and an
nRF52840 idle with its clock running a few µA. A leaf that listens all
the time draws its radio's receive current around the clock: about
two and a half weeks on a 2000 mAh cell. A leaf that wakes every five
minutes, sends a 15-byte poll (49 ms on `US915`, 55 ms on `EU868`) and
listens two seconds draws, by the same datasheets, around 50 µA on
average, and one that wakes every hour around 10 µA: years, where the
cell's own self-discharge matters more. These are estimates from
datasheet currents, not measurements: see [Not yet
measured](#not-yet-measured). They are why a leaf that sleeps is worth
a section: sensors and trackers that run on a small cell for a season,
and handhelds that last a trip, are what a mesh of fixed relays and
moving leaves is for.

**Why the leaf asks.** Three ways were considered to reach a radio
that is mostly off:

* *Sending at the receiver's time* (as LoRaWAN's class B does): every
  node keeps time with its neighbours, and a frame waits for a slot.
  Clocks drift on boards without a crystal kept for the purpose, and
  slots have to be agreed and kept.
* *Long preambles* (low-power listening): the receiver samples the
  channel briefly and often, and every sender sends a preamble longer
  than the gap between samples. Every frame to such a node, and every
  frame its neighbours send if they cannot tell who it is for, costs
  that preamble in airtime, which this protocol counts and caps
  ([the airtime budget](airtime.md)).
* *The receiver asks* (as Thread's sleepy end devices do, polling a
  parent): a parent holds frames until the child polls. It costs the
  child one short frame a wake and the parent some memory, and nobody
  else anything.

The third costs the shared channel least, and needs no clocks kept in
step. Its cost is delay: a frame waits up to `w` at the keeper.

**Why one keeper.** The leaf's [anchor](routing.md#leaves-that-move) is
already the relay through which routes to it go. Holding there needs
no new route: routes to a leaf already end at a relay next to it, and
naming that relay in the announce only stops the leaf's other relay
neighbours from trying to reach it directly, which would fail at every
try and count against the leaf as hops given up.

**Why a held notice.** Without one, the node before the keeper hears
nothing of a frame held and tries it twice more, then counts a hop
given up and tries the frame another way, every time. With one, the
hop ends as if the frame had been passed on. It is no more forgeable
than an acknowledgement, and a forged one costs what a forged
acknowledgement does: a source's retry.

**Why the source is told end to end.** No frame on the way to a sleeping
leaf carries its source, so a keeper cannot tell the source that its
message waits. Routes could say the destination sleeps, but a route's
entry has no spare bit and every node would learn every leaf's sleep.
The leaf telling its own contacts costs one small frame per contact,
reaches only those who send to it, and says nothing to anyone else.
A source that has not been told still has its message held and
delivered; it is only told too soon that it was given up.

**Why floods are left out.** A [group's](groups.md) frames are floods
with a blinded tag. A keeper cannot tell which of them a leaf wants
without the leaf telling it its groups, which would tell the keeper who
the leaf talks to. Holding every flood for every leaf would hold
everything. Unicast first; floods are [not yet
specified](#not-yet-specified).

**Why a relay may not sleep.** A relay that sleeps loses every frame
sent through it meanwhile, and its neighbours give up hops at it until
they forget it. A relay on a small cell should be a leaf.

## Not yet measured

* **Delivery.** How many messages to sleeping leaves arrive, and how
  late, in the simulator's scenarios, against leaves that listen all
  the time: at several `w`, and with leaves that move. Nothing here
  has been simulated.
* **`HOLD_LEAF`, and how much a keeper needs.** How many frames wait
  for a leaf at each `w`, and how many leaves a keeper keeps.
* **`LISTEN_MIN`.** Whether two seconds covers a poll's answer and the
  first held frame on a busy channel, given the answer's random wait
  and listening first.
* **Current drawn.** The estimates under [Rationale](#rationale) are
  from datasheets. What a board draws asleep, polling and listening
  needs measuring on each board the firmware supports.
* **The floor.** Samples arrive once a wake, not once an announce; the
  simulator's [recommendation](https://github.com/ternmesh/sim) leaves
  a floor for sleeping leaves as an open question.

## Not yet specified

* **Floods for a sleeping leaf**: a keeper that keeps the last few
  floods it passed on and replays them at a poll, or a leaf that tells
  its keeper which group tags to hold, at what that tells the keeper.
* **Signed polls and poll answers.** Anyone may send either. A forged
  poll makes a keeper hand over what it holds while the leaf sleeps:
  messages stay held, since their hops fail, but acknowledgements and
  first-contact frames, sent once, are lost and their sources try
  again. A forged answer can keep a leaf with a keeper that has gone.
* **What a client sees** ([Companion](companion.md#not-yet-specified)):
  turning sleeping on and off, choosing `w` and `l`, and the
  companion link itself, which a sleeping node cannot keep up over
  Bluetooth while its radio and processor sleep.
* **A keeper's own limits**: how many leaves one relay keeps, and
  whether a relay with no room says so in its answer to a solicit.
* **A sleeping leaf's own neighbours.** Its links to relays other than
  its keeper go down while it sleeps, as their margins are withdrawn;
  it finds them again by soliciting. Whether it should listen longer
  now and then to keep them is not said.
