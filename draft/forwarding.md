# Frames that follow routes

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It is how the
simulator ([ternmesh/sim](https://github.com/ternmesh/sim), candidate 3)
carries a message, written down, and every number in it is
**provisional**: a default the simulator settled on, not one measured on
radios.

[Routes](routing.md) defines how a node learns which neighbour to hand a
frame to. This section defines the frames that are handed on: what each
carries for the nodes that pass it along, how a node learns that the
next one has it, what it does when it has not, and how the node a
message came from learns that it arrived.

Test vectors: [`vectors/forwarding.json`](../vectors/forwarding.json),
produced by
[`vectors/tools/forwarding.py`](../vectors/tools/forwarding.py).

## Goals

1. **A message is sent, not flooded.** One node sends each frame to one
   neighbour. Nothing is broadcast to find the way, and the first
   message to a node costs what the hundredth does.
2. **The same bytes however far it goes.** What a frame carries for the
   nodes on its way does not grow with their number.
3. **No sender on the air.** A frame names the node it is for and the
   neighbour it is for now. It does not name where it came from.
4. **Lost frames are found by listening.** A node that has sent a frame
   hears its neighbour send it on. No acknowledgement is sent hop by
   hop.

Goal 3 is less than the [secured unicast frame](unicast-security.md)
asks, which is that nothing in clear names either end. See
[What an observer learns](#what-an-observer-learns).

## Notation

As in [Routes](routing.md): fields are big-endian, a routing id is four
bytes, `0x00000000` and `0xFFFFFFFF` are reserved. A **relay** forwards
other nodes' frames and a **leaf** does not. The **airtime** of a frame
is its time on air under the profile in use ([Radio settings](phy.md)).

## The head

Every frame that follows a route starts with eleven bytes:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | the frame's type |
| 1 | 1 | `hops` | nodes that may still pass it on |
| 2 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |
| 3 | 4 | `next` | the routing id of the neighbour it is for |
| 7 | 4 | `destination` | the routing id of the node it is for |
| 11 | 4 | `tag` | tells this frame from every other |

`hops`, `power` and `next` change at every node. Nothing after them
does.

Two types are defined:

| `hdr` | Frame | After the head |
|---|---|---|
| `0x48` | a **message**: a secured unicast frame | `tag` is its destination tag; then its ciphertext and check |
| `0x50` | an **acknowledgement** | `tag` is that of the message it answers; then 4 bytes, `proof` |

A message is at least 23 bytes: the head, the tag and the 8-byte check
of an empty message. An acknowledgement is exactly 19 bytes. A receiver
MUST discard a message shorter than 23 bytes, an acknowledgement of any
other length, and a frame whose `next` or `destination` is a reserved
id.

**The same frame.** Four bytes of tag do not tell every message from
every other: two in the air at once share one now and then. So two
frames are **the same frame** only if they are of one length and every
byte from `destination` on is equal, which for a message takes in its
ciphertext and check. `tag` is only where an acknowledgement is matched
to its message, since an acknowledgement carries nothing else of it.

In the [secured unicast frame](unicast-security.md) as first drafted,
`hop` and `label` held three bytes for this layer. Bytes 1 to 10 here
take their place, so that frame's overhead is 23 bytes, not 16, and its
destination tag is at offset 11. Its `hdr` and destination tag are
authenticated as before; `hops`, `power`, `next` and `destination` are
not. That section and its vectors are still to be changed to match.

## Sending

A node with a frame for a destination looks up its
[selected route](routing.md#selecting-a-route). The frame goes to that
route's neighbour, with `next` set to it, `hops` set to `HOP_MAX` if
the frame is the node's own, and `power` set to what it is sent at.

**How loud.** A frame goes at its neighbour's floor plus
`POWER_MARGIN`, as [Routes](routing.md#power-for-every-neighbour) has
it, plus the neighbour's **boost** (below), rounded up and kept between
the node's lowest power and its full power. A frame sent in answer to
one received — one passed on, or an acknowledgement — MUST go no
quieter than the node it came from needs: that node listens for it. What
it needs is reckoned from the one frame received, as a floor's first
sample is: `power - (snr - SNR_FLOOR) + POWER_MARGIN`.

**When.** A frame sent in answer to one received waits a random time,
uniform up to `JITTER` airtimes of itself, before it is offered to the
radio. The nodes that heard the same frame would otherwise answer at
the same instant. A node with several frames ready sends
acknowledgements first, then frames it is passing on, then its own.

## Receiving

A node that receives a frame first checks whether it
[ends a hop](#hops) of its own. Then:

1. An acknowledgement whose `destination` is the node's own id is for
   it, whatever its `next`: see [Messages](#messages).
2. A frame whose `next` is not the node's id is otherwise ignored.
3. A message whose `destination` is the node's id is for it.
4. Anything else is to be passed on. A leaf MUST NOT pass a frame on.
   A relay MUST NOT pass on a frame whose `hops` is 0 or 1. A relay
   that already holds [the same frame](#the-head) and has not finished
   with it MUST ignore the copy: the node before will hear it pass the
   first on. Otherwise the relay sends it as
   [above](#sending), with `hops` one less.

A relay with no route for a frame drops it, and
[asks for a route](routing.md#starving-and-asking) to its destination.

A relay has room for only so many frames at once. One that arrives when
there is none is dropped.

## Hops

A node that has sent a frame to a neighbour **listens**. The hop has
succeeded when the node receives:

* [the same frame](#the-head), with `hops` one less than it sent; or
* for a message, any acknowledgement with the message's `tag`.

An acknowledgement for another message with the same tag ends the hop
too, wrongly, once in 2^32 for each pair of messages a node hears at
once. The message is then not sent again from that node, and its source
sends it again as for any other loss: the source is not deceived,
[checking `proof`](#messages) against its own message.

It listens for `HOP_WAIT` plus twice the frame's airtime, from when the
frame went on the air. Without either, it sends the frame again, up to
`HOP_RETRIES` times, each `STEP` louder than the last and never louder
than its full power. After the last it **gives the hop up**.

The last hop of an acknowledgement, to the node it is for, has nothing
to hear, and is sent once.

A node that still holds a frame it has sent, when it hears that the hop
succeeded, MUST NOT send it again. A copy not yet on the air SHOULD be
withdrawn.

**What a hop teaches.** A frame heard passed on came from the
neighbour it was sent to. The node takes its `power` and
signal-to-noise ratio as it would an announce's
([Links](routing.md#links)): a sample for the neighbour's floor, and
proof that it was heard just now. It also takes 1 dB off the
neighbour's boost. An acknowledgement that ends a message's last hop
teaches the same, if its `hops` is `HOP_MAX`: only then did the
destination itself send it.

**A hop given up.** The neighbour's boost goes up by `STEP`, and never
above the node's full power less its lowest. A neighbour with
`DEAD_HOPS` hops given up in a row, and nothing heard from it between,
is gone: the node MUST forget it, and every route through it. Fewer are
no evidence. Frames are lost to a busy channel far more often than to a
dead neighbour.

**Another way.** A message whose hop is given up is not yet lost. If
the node holds another route to its destination that is
[feasible](routing.md#selecting-a-route), through a neighbour it may
use and has not given this frame up at, it sends the frame there, with
its retries anew: the best such route, up to `SALVAGE` times a frame.
Feasible routes cannot lead back. An acknowledgement is not sent
another way.

## Messages

**The destination** of a message opens it as the
[secured unicast frame](unicast-security.md#receiving) says, and
answers with an acknowledgement to the node it came from, which it
knows from the session the tag belongs to. It answers every copy it
receives: an acknowledgement is one frame, and as easily lost as any.
So a destination MUST keep, for the messages it accepted most recently,
what it needs to acknowledge them again, since a copy of a message
already accepted is in no window.

`proof` shows that the destination, and no node on the way, sent the
acknowledgement. For message `n` in direction `d`:

```
proof = AES(TK_d, 0^11 || 0x01 || u32be(n))[0..4]
```

with `TK_d` the direction's tag key. The destination tag is the same
with `0x00` in place of `0x01`, so neither gives the other. Only the
two ends hold `TK_d`. A node on the way that claims a message arrived
has one chance in 2^32 for each try.

**The source** keeps a message until it is acknowledged. It waits

```
ACK_WAIT + ACK_FACTOR × the route's metric, in milliseconds
```

from when the message first goes on the air: the metric is airtime, so
this is a few journeys there and back. Without a valid acknowledgement
by then it starts the message again — the same frame, with `hops` at
`HOP_MAX`, on whatever route it has now, whatever had become of the
copy before — up to `RETRIES` times. After the last wait it gives the
message up and tells the application.

A source with no route asks for one, as a relay does, and counts that
as a try, waiting `ACK_WAIT`.

Once a message is acknowledged or given up, nothing of it goes on the
air from its source again.

A source that has sent a message to the same neighbour more than
`HOP_RETRIES` times, over however many tries, and never heard it passed
on, counts that as a hop given up.

## Parameters

| Name | Value | |
|---|---|---|
| `HOP_MAX` | 32 | as in Routes |
| `HOP_WAIT` | 4 s | |
| `HOP_RETRIES` | 2 | so a hop is sent three times |
| `STEP` | 3 dB | |
| `DEAD_HOPS` | 24 | |
| `SALVAGE` | 1 | |
| `JITTER` | 2 | airtimes, as in Routes |
| `ACK_WAIT` | 5 s | |
| `ACK_FACTOR` | 4 | |
| `RETRIES` | 3 | so a message is tried four times |

## Conformance

An implementation conforms to this section if, for
[`vectors/forwarding.json`](../vectors/forwarding.json):

* **heads:** it builds `frame` from the fields given, and reads the
  fields from `frame`;
* **rejected:** it discards each `frame`;
* **hops:** having sent the frame `sent`, it finds that receiving the
  frame `heard` ends the hop, or not, as `ends` says;
* **backs:** having received a frame sent at `power` and heard at
  `snr_quarter_db`, at `spreading_factor`, with `lowest` and `full` its
  own lowest and full power, it finds that its answer must go at
  `needs` or more;
* **powers:** with `neighbour` what Routes gives for the frame's
  neighbour, its boost included, `back` what the node the frame came
  from needs (`null` for a frame that answers none), and `full` its
  full power, it sends the frame for the `try`-th time, from 0, at
  `power`.

`proof` has no vector yet: it comes with the secured unicast frame's
change to this head. When frames go depends on random times and on what
is heard, and is checked by running implementations against each other
and against the simulator.

## What an observer learns

An observer who hears a frame learns the routing id of the node it is
for and of the neighbour passing it on. A routing id is a fixed hash of
an address, so anyone who knows an address knows when that node is
being written to. The observer does not learn who wrote. But an
acknowledgement goes back to the writer by the same rules, with the
same `tag`, so an observer who hears both has both ends.

Announces already give every node's routing id and its neighbours'. So
does every frame here. What would hide them is routing ids that change,
which Routes lists as not yet specified, and which would cover
announces and these frames at once. A label in place of the
destination, handed out in announces, was considered and set aside: an
observer who hears the announce maps the label back.

For comparison, as their public documentation has it: a Meshtastic
packet names both ends in clear by fixed node numbers, and a MeshCore
direct message carries a one-byte hash of each end's key and the list
of repeaters on its path.

## Rationale

**Why this, measured.** The firmware's implementation of this section
and of Routes, run in the simulator beside the incumbents' as the
simulator ports them, with 1000 nodes of which 200 relay, a message from
each node every half hour to another at random, and a minute to arrive
in. Messages that arrived in time, and how many did for each second on
the air, all nodes together (three seeds):

| | All on SF7, 125 kHz | Each on its own preset |
|---|---|---|
| Meshtastic | 19.0%, 0.013 | 1.1%, 0.001 |
| MeshCore | 30.3%, 0.026 | 5.7%, 0.004 |
| This, 255 neighbours kept | 96.7%, 0.44 | 14.4%, 0.013 |
| This, 64 neighbours kept | 95.2%, 0.32 | 11.6%, 0.010 |

And in a town of 200 nodes at SF9, every node a relay: 100.0% with 255
neighbours kept and 99.9% with 64, against 21.0% for Meshtastic.

There is no broadcast in these runs, since this specification has none
yet, and the incumbents are built around it. The radio model's capture
and isolation figures are from the literature, not a bench.

**Why the source's wait does not wait for its hop.** A first version
let a message's first hop run out its retries, and another way, before
the message was tried again. A message that could not arrive then
stayed on the air for two minutes, and on the slow preset, where the
channel is full, 4.2% arrived in time; with the wait fixed, as above,
14.4%.

**Why listen, and not acknowledge each hop.** The next node sends the
frame anyway. Hearing it costs nothing, and an acknowledgement for each
hop would double the frames.

**Why `power` is in the head.** A node passing a frame on must be heard
by the node before it, which has turned its own power down to reach
only its neighbour. With no sender in the frame, the power it was sent
at and the strength it arrived with are all there is to reckon that
from.

**Why 24 hops given up, and not 3.** In the simulator, forgetting a
neighbour sooner delivered less with every node up and less with a
quarter of the relays going down and coming back: at 3, 6 and 12 hops
it was worse at each step than at 24. The false alarms outweigh the
dead found sooner.

## Not yet measured

* **Any of the parameters, on radios.**
* **How often a node hears its neighbour pass a frame on**, on real
  links: the next hop may be heard and its own next hop not.
* **Memory**: each frame in hand is a whole frame and some thirty bytes.

## Not yet specified

* **The secured unicast frame with this head**: its section and vectors
  still give the three bytes first drafted.
* **Routing ids that change** ([above](#what-an-observer-learns)).
* **Which messages a destination keeps to acknowledge again**, and for
  how long.
* **A flood when the routes are stale.** The simulator floods a message
  given up at a leaf that has moved, through relays, a few hops. It
  needs broadcast, which is not specified.
* **Broadcast**, and messages to groups.
* **Fragments**: a message is one frame.
* **Priority** between messages, and a share of the air for each node.
