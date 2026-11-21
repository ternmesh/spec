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
   neighbour it is for now. It does not name where it came from, but
   for the first frame of a handshake and a [trace](#traces), which
   have to.
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

Six kinds of frame are defined:

| `hdr` | Frame | After the head |
|---|---|---|
| `0x48`, `0x49` | a **message**: a secured unicast frame, for the node's user or, with the low bit set, [for the node](unicast-security.md#the-frame) | `tag` is its destination tag; then its ciphertext and check |
| `0x50` | an **acknowledgement** | `tag` is that of the message it answers; then 4 bytes, `proof` |
| `0x51` to `0x54` | a **first-contact frame**, one of a handshake's four | `tag` is its contact tag; then, for `0x51`, the 4-byte routing id it came from; then the handshake's message |
| `0x55` | a **held notice**, from the keeper of a [leaf that sleeps](sleeping.md#holding) | `next` is the keeper's own id, not the next node's; `tag` is that of the frame it holds; nothing after |
| `0x56` | a **trace** | `tag` is the trace's own; then `from`, the routing id it came from, and its [entries](#traces) |
| `0x57` | a **trace answer** | `tag` is that of the trace it answers; then `flags`, `out`, and its [entries](#traces) |

A message is at least 23 bytes: the head, the tag and the 8-byte check
of an empty message. An acknowledgement is exactly 19 bytes, and a held
notice exactly 15. A
first-contact frame is exactly 56, 60, 80 or 24 bytes, for `0x51` to
`0x54` ([First contact](first-contact.md#the-frame)). A trace is 19
bytes and 5 more for each entry, and a trace answer 17 and 5 more for
each entry, within the entries [Traces](#traces) allows. A receiver
MUST discard a message shorter than 23 bytes, an acknowledgement, a
held notice, a first-contact frame, a trace or a trace answer of any
other length, and a frame whose `next` or
`destination` is a reserved id.

**The same frame.** Four bytes of tag do not tell every message from
every other: two in the air at once share one now and then. So two
frames are **the same frame** only if they are of one length, have one
`hdr`, and every byte from `destination` on is equal, which for a
message takes in its ciphertext and check. `tag` is only where an acknowledgement is matched
to its message, since an acknowledgement carries nothing else of it.

Bytes 1 to 10 are what the
[secured unicast frame](unicast-security.md#the-frame) and the
[first-contact frame](first-contact.md#the-frame) call `route`,
and leave to this section. That frame's `hdr` and destination tag are
authenticated end to end; `hops`, `power`, `next` and `destination` are
not.

## Sending

A node with a frame for a destination looks up its
[selected route](routing.md#selecting-a-route). The frame goes to that
route's neighbour, with `next` set to it, `hops` set to `HOP_MAX` if
the frame is the node's own, and `power` set to what it is sent at.

**How loud.** A frame goes at its neighbour's floor plus
`POWER_MARGIN`, as [Routes](routing.md#power-for-every-neighbour) has
it, plus the neighbour's **boost** (below), rounded up and kept between
the node's lowest power and its full power. A frame sent in answer to
one received — one passed on, an acknowledgement, or a first-contact
frame that answers another — MUST go no
quieter than the node it came from needs: that node listens for it, or
for a first-contact frame is most often the node the answer goes to
next, which no table knows better than the frame just heard. What
it needs is reckoned from the one frame received, as a floor's first
sample is: `power - (snr - SNR_FLOOR) + POWER_MARGIN`.

**When.** A frame sent in answer to one received waits a random time,
uniform up to `JITTER` airtimes of itself, before it is offered to the
radio. The nodes that heard the same frame would otherwise answer at
the same instant. A node with several frames ready sends
acknowledgements first, then frames it is passing on, then its own.

**Paid for.** Every frame here is paid for from the node's
[airtime budget](airtime.md#spending), which says when a frame of the
node's own waits and when one it would pass on is dropped.

## Listening first

A node MUST NOT start to send a frame while its radio is **receiving**
one. This holds for every frame a node sends, those of
[Routes](routing.md) and of [first contact](first-contact.md) as well
as these.

A radio is receiving from when it finds a preamble until the first of:

* the radio says the frame has ended, whether it arrived whole or not;
* the profile's preamble and `HEAD_WAIT` symbols after the preamble was
  found, if the radio has found no header by then. A preamble with no
  header after it is noise, or a frame with another network's sync
  word;
* the airtime of the longest frame, 255 bytes, after the preamble was
  found: a radio that never says a frame has ended does not hold its
  node for ever.

A preamble found while the radio waits for a header starts the wait
again, and a header found when the radio is not receiving, with no
preamble before it or one whose wait has run out, counts as both. A node
that starts to send is no longer receiving.

A node held back MAY send as soon as its radio is no longer receiving.
It does not owe the channel a further wait: the random waits above
already keep apart the frames that would otherwise go together.

A node asks its radio as late as it can. Between asking and the first
symbol of the frame it SHOULD let no more than `LOOK` pass.

This is not a promise that the channel is clear. A radio does not find
a frame too weak for it to receive, or one that began while it was
sending, and it takes several symbols to find any. Frames still meet,
and the rest of this section is what recovers them.

## Receiving

A node that receives a frame first checks whether it
[ends a hop](#hops) of its own. Then:

1. An acknowledgement whose `destination` is the node's own id is for
   it, whatever its `next`: see [Messages](#messages).
2. A frame other than a held notice whose `next` is not the node's id
   is otherwise ignored.
   A held notice ends a hop of this node's, if it ends one (its
   `next` names the keeper that sent it, not this node), and is
   otherwise ignored: no node passes one on.
3. A message, a first-contact frame, a trace or a trace answer whose
   `destination` is the node's id is for it. A trace is answered, and a
   trace answer ends a trace, as [Traces](#traces) says.
4. Anything else is to be passed on. A leaf MUST NOT pass a frame on.
   A relay MUST NOT pass on a frame whose `hops` is 0 or 1. A relay
   that already holds [the same frame](#the-head) and has not finished
   with it MUST ignore the copy: the node before will hear it pass the
   first on. Otherwise the relay sends it as
   [above](#sending), with `hops` one less, and a trace or a trace
   answer with [its entry](#traces) added.

A relay with no route for a frame drops it, and
[asks for a route](routing.md#starving-and-asking) to its destination.

A relay has room for only so many frames at once. One that arrives when
there is none is dropped.

## Hops

A node that has sent a frame to a neighbour **listens**. The hop has
succeeded when the node receives:

* [the same frame](#the-head), with `hops` one less than it sent, and
  for a trace or a trace answer with [one entry](#traces) more; or
* for a message, any acknowledgement with the message's `tag`, and for
  a trace, any trace answer with the trace's `tag`; or
* a [held notice](sleeping.md#holding) from that neighbour, with the
  frame's `destination` and `tag`: the neighbour is the keeper of a
  leaf that sleeps, and holds the frame for it.

An acknowledgement for another message with the same tag ends the hop
too, wrongly, once in 2^32 for each pair of messages a node hears at
once. The message is then not sent again from that node, and its source
sends it again as for any other loss: the source is not deceived,
[checking `proof`](#messages) against its own message. No node on the
way can check `proof`, so an acknowledgement forged by a node in
earshot ends a hop in the same way, and costs the message the same
retry from its source.

It listens for `HOP_WAIT` plus twice the frame's airtime, from when the
frame went on the air. Without either, it sends the frame again, up to
`HOP_RETRIES` times, each `STEP` louder than the last and never louder
than its full power. After the last it **gives the hop up**.

**Again, but not at once.** A frame sent again, here or
[from its source](#messages), first waits a random time, uniform up to
`RETRY_JITTER` airtimes of itself. What lost it may have been another
node's frame, sent at the same moment: that node waits as long as this
one, and without the random time the two would meet again at every
try.

The last hop of an acknowledgement, of a first-contact frame or of a
trace answer, to the node it is for, has nothing to hear, and is sent
once: a node listens for every frame it sends but those.

A node that still holds a frame it has sent, when it hears that the hop
succeeded, MUST NOT send it again. A copy not yet on the air SHOULD be
withdrawn.

**What a hop teaches.** A frame heard passed on came from the
neighbour it was sent to. The node takes its `power` and
signal-to-noise ratio as it would an announce's
([Links](routing.md#links)): a sample for the neighbour's floor, and
proof that it was heard just now. It also takes 1 dB off the
neighbour's boost. An acknowledgement teaches nothing better, even one
that ends a hop: a node MUST NOT take from one anything but a worse
sample, below, nor anything off a boost. No node on the way can check
it, and anyone can send one.

**Who sent it.** The head names the node a frame is for, not the one
that sent it. A node knows the sender of a frame it hears only:

* of [the same frame](#the-head) heard passed on, one hop further: the
  neighbour it sent it to, as above;
* of an acknowledgement whose `hops` is `HOP_MAX`, with the `tag` of a
  message this node sent to that message's own destination as the next
  hop: that destination, which made it;
* of a message for this node whose `hops` is `HOP_MAX`, which it accepts
  or takes as a [copy](#messages): its source, whose session says who it
  is;
* of a message passed on to this node whose `hops` was `HOP_MAX`: its
  source, which this node learns only when an acknowledgement with the
  message's `tag` comes back for it to pass on to its destination, that
  source, as the next hop.

A relay passing such an acknowledgement on SHOULD send it no quieter
than that message's source needed, by the one frame it heard
([How loud](#sending)), if it still holds what that was: the source
listens for it, and the relay's floor for it may be from long ago.

From each of the last three, if it keeps the sender as a neighbour, a node
takes a [worse sample](routing.md#links), which can make the link look
worse and never better. From any other frame it takes nothing of the
link.

**A hop given up.** The neighbour's boost goes up by `STEP`, and never
above the node's full power less its lowest. A neighbour with
`DEAD_HOPS` hops given up in a row, and nothing heard from it between,
is gone: the node MUST forget it, and every route through it. Fewer are
no evidence. Frames are lost to a busy channel far more often than to a
dead neighbour.

**Another way.** A message or a first-contact frame whose hop is given
up is not yet lost. If
the node holds another route to its destination that is
[feasible](routing.md#selecting-a-route), through a neighbour it may
use and has not given this frame up at, it sends the frame there, with
its retries anew: the best such route, up to `SALVAGE` times a frame.
Feasible routes cannot lead back. A leaf with no such route that takes
[default routes](routing.md#a-leafs-default-route) sends the frame
to its nearest relay it has not given this frame up at, in the same way
and within the same `SALVAGE`. An acknowledgement, a trace and a trace
answer are not sent another way: a trace shows the route a node has
selected, and one sent another way would show another. Which way an
acknowledgement goes first is [below](#messages).

## Messages

**The destination** of a message opens it as the
[secured unicast frame](unicast-security.md#receiving) says, and
answers with an acknowledgement to the node it came from, which it
knows from the session the tag belongs to. It answers copies too, as
below: an acknowledgement is one frame, and as easily lost as any.

**A route round a neighbour.** A node's **route round** a neighbour `X`
to a destination is, of the routes it holds to the destination through
neighbours it may [use](routing.md#roles) other than `X`, whether or
not they are [feasible](routing.md#selecting-a-route): one through a
neighbour at which no [hop has been given up](#hops) since it last
heard from it, if there is one; of those, the one with the lowest
metric; of two as low, either. A leaf that holds none, and takes
[default routes](routing.md#a-leafs-default-route), takes its nearest
relay other than `X`. A route round no neighbour is the same with no
`X`. Only a frame's first hop is ever chosen so: the relays pass it on
by their own selected routes.

**Which way the acknowledgement goes.** It goes by the destination's
[selected route](routing.md#selecting-a-route) to the message's source,
as any frame, but in two cases. In them it goes instead by the
destination's route round the source. The two cases:

* the selected route's neighbour is the source itself, and the message
  arrived with `hops` below `HOP_MAX`: a relay passed it on, so the
  source did not send it here direct;
* the destination has no route to the source it may use, and none it
  takes by default.

With no such route either, it goes as it would have: by the selected
route, or, with none, not at all. A keeper's acknowledgement to a
[sleeping leaf it keeps](sleeping.md#holding) goes as that section
says, and not by this. Only the acknowledgement's first hop is chosen
so: a relay passes it on by its own selected route, as any frame.

**A copy** is a message frame that the destination does not accept, of
the same length and `hdr` as a message it has accepted, in any session
it holds, with that message's destination tag, the same first four
bytes of AEAD tag, and a counter no more than 31 below that direction's
`H`. A destination MUST acknowledge a copy as it did the message,
unless it has already sent `COPY_ACKS` acknowledgements of that
message, the first among them, or more than `COPY_TIME` has passed
since it accepted it. It MUST NOT accept a copy, nor acknowledge any other frame
it does not accept.

Four bytes of tag, and four of AEAD tag, can be those of more than one
such message, in two sessions or in one, and nothing else in a copy
says which it is a copy of. So a destination MUST acknowledge every one
of them that it still answers, each with its own `proof` and to its own
session's other end: one of the acknowledgements is the one that was
lost, and the others are copies of acknowledgements already sent, which
their sources ignore or have no more use for.

So for each counter it has accepted, for as long as it is within 31 of
`H`, a destination keeps the first four bytes of its AEAD tag, its
length and `hdr`, when it was accepted, and how many acknowledgements
of it have gone, and keeps the [tag key](unicast-security.md#keys) of
its epoch, which gives its tag and its `proof`. A copy is not opened:
its message key may be erased by then.

A copy shows what an acknowledgement shows: that the destination has
the message, and where the node that sent it is, since the
acknowledgement goes there. Anyone who heard a message can send it
again, as often as they like and from anywhere. A destination that
answered every copy would tell a stranger far from the message's path
where its sender is, for as long as the session lasted, and would send
an acknowledgement the length of the path back for each frame the
stranger sent. `COPY_ACKS` bounds what one message can be made to cost,
and `COPY_TIME` how long after it went it can tell anyone anything. The
AEAD tag means that a copy has to be the message itself: a frame with
only its destination tag, which anyone who heard the message knows, is
not answered.

`proof` shows that the destination, and no node on the way, sent the
acknowledgement. For message `n` in direction `d`:

```
proof = AES(TK_d(e), 0^11 || 0x01 || u32be(n))[0..4]
```

with `TK_d(e)` the tag key of the epoch `n` is in. The destination tag
is the same with `0x00` in place of `0x01`, so neither gives the other.
Only the two ends hold `TK_d(e)`. A node on the way that claims a
message arrived has one chance in 2^32 for each try.

**The source** keeps a message until it is acknowledged. It waits

```
ACK_WAIT + ACK_FACTOR × the route's metric, in milliseconds
```

from when the message first goes on the air: the metric is airtime, so
this is a few journeys there and back. For a destination that has said
it [sleeps](sleeping.md#telling-the-source), it waits longer, as that
section says. An acknowledgement is **valid**
for a message if its `tag` is the message's destination tag and its
`proof` is the one above for the message's direction and counter; a
source MUST NOT take any other as showing that a message arrived. It
keeps the tag key of the message's epoch while it waits, as
[the secured unicast frame](unicast-security.md#keys) allows. Without
a valid acknowledgement
by then it starts the message again — the same frame, with `hops` at
`HOP_MAX`, on whatever route it has now, whatever had become of the
copy before, and [not at once](#hops) — up to `RETRIES` times. If no
hop of the try that ended succeeded at its first neighbour — nothing
heard passed on, no acknowledgement, no held notice — the next try
avoids that neighbour: it goes by the source's route round it, and
with none, by the route it has. After
the last wait it **gives the message up** and tells the application.
A message given up counts toward
[starting the session again](unicast-security.md#starting-again).

A source with no route, and none it takes
[by default](routing.md#a-leafs-default-route), asks for one, as a
relay does. Meanwhile, each try goes by its route round no neighbour,
if it holds one; with none, it counts asking as a try, waiting
`ACK_WAIT`.

Once a message is acknowledged or given up, nothing of it goes on the
air from its source again.

A try whose first hop never succeeded — nothing heard passed on, no
acknowledgement, no held notice — counts as a hop given up at that
neighbour, as any other: it raises the boost, and counts toward
`SOLICIT_HOPS` and `DEAD_HOPS`. A try is two sends at rising power and
a wait of a few journeys, what a hop's own sends are.

**First contact.** The node that begins a handshake keeps each of its
two frames as a source keeps a message, with the next frame of the
handshake in the acknowledgement's place:
[First contact](first-contact.md#sending-again) has the rules. One
thing differs. A first-contact frame sent to the node it is for is not
listened for, so however often it goes unanswered, that is not a hop
given up: a node may choose not to answer.

## Traces

A **trace** finds the way a node's frames take to a destination: which
relays pass them on, and how well each hears the one before. It goes
out as a message would, and each node it reaches adds an **entry**;
its destination answers it with a **trace answer**, which comes back
the same way, gathering entries of its own. It is for a person who
wants to know why a message is slow, or did not arrive, and for
testing a mesh.

**The frames.** After the head and the tag, a trace carries:

| Offset | Bytes | Field | |
|---|---|---|---|
| 15 | 4 | `from` | the routing id of the node that began it |
| 19 | 5 each | entries | as below, in the order they were added |

and a trace answer:

| Offset | Bytes | Field | |
|---|---|---|---|
| 15 | 1 | `flags` | who answered, below |
| 16 | 1 | `out` | how many of its entries the trace gathered on the way out |
| 17 | 5 each | entries | the trace's `out` entries, then those added on the way back |

An **entry** is a routing id, 4 bytes, and the signal-to-noise ratio
at which that node heard the frame it added the entry to, as an `i8` in
quarters of a dB, rounded towards zero and kept between -128 and 127.
A trace carries at most `TRACE_ENTRIES` entries, and a trace answer at
most `TRACE_ENTRIES` after its first `out`, with `out` itself at most
`TRACE_ENTRIES`. A receiver MUST discard a trace answer whose `out` is
more than the entries it carries, or whose `flags` is reserved.

`flags` is 0 if the trace's destination answered it, 1 if the
destination's keeper answered it because the destination
[sleeps](sleeping.md), and 2 if a relay answered it because it had no
route to the destination. The other values are reserved.

**Beginning one.** A node begins a trace with a `tag` of four random
bytes, `from` its own routing id, and no entries, and sends it as its
own frame. It holds no more than one trace at a time to any one
destination. With no route, it asks for one, as for a message, and
gives the trace up if none comes within `ACK_WAIT`. Otherwise it waits

```
ACK_WAIT + ACK_FACTOR × the route's metric × 2, in milliseconds
```

from when the trace first went on the air, twice a message's wait,
since each node on the way adds its entry, and then gives it up. A
trace is not begun again: its source tells the application that it was
not answered, and the application may begin another.

**On the way.** A node that receives a trace or a trace answer whose
`next` is its own id adds its entry, its own routing id and how well it
heard the frame, to the end, before anything else it does with it.
A relay that passes it on sends the frame with its entry added and
`hops` one less, and the hop is ended by the frame heard with the next
node's entry added ([Hops](#hops)). A node that would have to add an
entry beyond what the frame may carry drops it: a relay does not pass
it on, and no node answers it. The node that ends a trace adds its
entry only for its application, and not to any frame, so its entry is
never beyond what one may carry.

**Answering.** The node that answers a trace adds its entry first. Then
it sends, as its own frame, a trace answer whose `destination` is the
trace's `from`, whose `tag` is the trace's, whose `flags` say who
answered, and whose `out` and entries are the trace's entries, its own
the last of them. The trace is answered:

* by its destination, with `flags` 0;
* by a relay that keeps the destination, a leaf that is asleep
  ([Holding](sleeping.md#holding)), with `flags` 1: a keeper does not
  hold a trace for its leaf. The answer ends where frames for the leaf
  wait, which is what the trace can show; and
* by a relay that has no route to the destination and would drop the
  trace ([Receiving](#receiving)), with `flags` 2, if it has a route to
  `from`. It asks for a route to the destination all the same.

A node answers no more than `TRACE_ANSWERS` traces a minute, as each of
the three, and drops those beyond. A leaf MUST NOT answer a trace whose
`from` is not the routing id of a node it shares a
[session](first-contact.md) with: a stranger learns nothing of where a
leaf is from a trace to it but the relay that last had a route. Any
node MAY decline to answer a trace, and drops it.

**Ending one.** A trace answer whose `destination` is the node's own id
and whose `tag` is that of a trace the node holds ends that trace: the
node adds its own entry, as on the way, and tells the application the
entries, `out` and `flags`. It ignores any later answer with the same
`tag`, and any whose `tag` is no trace's it holds.

**What it shows.** The entries name, in order, the nodes that passed the
trace on and the node that answered, then the nodes that passed the
answer on and the node that began it, each with how well it heard the
node before. The number of each is how many hops each way took. A
trace's entries are not authenticated: any node on the way can write
what it likes into them, and any node that heard the trace can answer
it. A trace shows how a mesh carries frames, and proves nothing.

**Paid for.** A trace and a trace answer are paid for as a message is
([Paid for](#sending)): a node's own waits for its budget, and one it
would pass on is dropped. A relay of an earlier draft does not know
them, and drops them: a trace through one is never answered.

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
| `RETRY_JITTER` | 4 | airtimes |
| `ACK_WAIT` | 5 s | |
| `ACK_FACTOR` | 4 | |
| `RETRIES` | 3 | so a message is tried four times |
| `COPY_ACKS` | 4 | `RETRIES` + 1: acknowledgements of one message, the first among them |
| `COPY_TIME` | 600 s | longer than a source keeps trying on the longest route a metric describes: four waits of `ACK_WAIT + ACK_FACTOR × 0x7FFE` ms are 544 s |
| `HEAD_WAIT` | 13 | symbols: the 4.25 that end a preamble and the 8 that hold a header, rounded up |
| `LOOK` | 5 ms | |
| `TRACE_ENTRIES` | 16 | entries each way; a trace answer is then at most 177 bytes |
| `TRACE_ANSWERS` | 4 | traces a minute a node answers, as each of destination, keeper and relay with no route |

## Conformance

An implementation conforms to this section if, for
[`vectors/forwarding.json`](../vectors/forwarding.json):

* **heads:** it builds `frame` from the fields given, and reads the
  fields from `frame`;
* **rejected:** it discards each `frame`;
* **hops:** having sent the frame `sent`, it finds that receiving the
  frame `heard` ends the hop, or not, as `ends` says, and takes it as a
  sample of the neighbour's floor, or not, as `teaches` says;
* **waits:** having sent the frame `sent`, it listens for the hop to
  succeed and sends the frame again if it does not, or sends it once,
  as `listens` says;
* **entries:** receiving the trace or trace answer `frame` as the relay
  `id`, heard at `snr_quarter_db`, it passes on a frame whose `hops`
  is `hops` and whose bytes from `destination` on are `passed`, or
  drops it, where `passed` is `null`;
* **answers:** receiving the trace `frame` as the node `id`, heard at
  `snr_quarter_db`, as its destination, as the keeper of its
  destination asleep, or as a relay with no route to it, as `as` says,
  it answers with a trace answer whose `hops` is `HOP_MAX` and whose
  bytes from `destination` on are `answer`;
* **backs:** having received a frame sent at `power` and heard at
  `snr_quarter_db`, at `spreading_factor`, with `lowest` and `full` its
  own lowest and full power, it finds that its answer must go at
  `needs` or more;
* **powers:** with `neighbour` what Routes gives for the frame's
  neighbour, its boost included, `back` what the node the frame came
  from needs (`null` for a frame that answers none), and `full` its
  full power, it sends the frame for the `try`-th time, from 0, at
  `power`;
* **agains:** sending a frame of `length` bytes again at
  `spreading_factor` and `bandwidth_hz`, as a hop that heard nothing of
  it (`hop`) or as its source with no acknowledgement (`source`), it
  first waits no longer than `longest_ns`, and not the same time at
  every try;
* **listens:** with a radio at `spreading_factor` and `bandwidth_hz`
  that finds a preamble (`preamble`) or a header (`header`), says a
  frame has ended (`end`), or is given a frame to send (`sent`) at
  each of the times in `events`, it finds at each time in `asks`, every
  event at or before that time having happened, that it may not start
  to send, or may, as `receiving` says.

* **retried:** as the source of a message, holding the `routes` given
  to its destination, as in **acknowledged**, its last try having gone
  first to `last` and been heard there or not (`heard`), it sends the
  next try first to `next_after`;
* **attributed:** having sent the message `sent` to the neighbour its
  `next` names, and then received the acknowledgement `heard`, it takes
  a worse sample of that neighbour or of none, as `from` says (`next`
  or `null`); and as the destination of a message it accepts, heard
  with `hops`, of its source or of none (`source` or `null`);
* **acknowledged:** as the destination of a message that arrived with
  `hops`, a leaf or not (`leaf`), with `nearest` its nearest relay if
  it is a leaf that takes default routes (`null` for none), holding
  the `routes` given to the message's `source`, each through the
  neighbour `next`, a relay or not, that it may use or not
  (`usable`), feasible or not, with its `metric`, and `selected`
  the index of the one selected (`null` for none), it sends the
  acknowledgement to `next_after` (`null` for none).

and, for
[`vectors/unicast-security.json`](../vectors/unicast-security.json),
which holds the cases that need a session's keys:

* **acknowledgements:** as the node that sent message `counter` in
  `direction` of the session `session_secret`, it takes `frame` as
  showing that the message arrived, or not, as `valid` says;
* **sequences:** as that file's receiver, given each delivery at
  `at_s` seconds, it acknowledges exactly the deliveries whose
  `acknowledge` is true, each with the delivered frame's tag and that
  `proof`. A delivery acknowledged and not accepted is a copy;
* **collisions:** as that file's receiver, for each delivery it sends
  exactly the acknowledgements in `acknowledge`, in any order: for each,
  the delivered frame's tag and that `proof`, to the other end of that
  `session`. A copy whose tag two accepted messages share is
  acknowledged for the one whose AEAD tag it shares, and not for the
  other.

When frames go depends on random times and on what is heard. A case
can hold a random time's bound, as `agains` does, and not that it is
uniform; the rest is checked by running implementations against each
other and against the simulator.

## What an observer learns

An observer who hears a frame learns the routing id of the node it is
for and of the neighbour passing it on. A routing id is a fixed hash of
an address, so anyone who knows an address knows when that node is
being written to. The observer does not learn who wrote. But an
acknowledgement goes back to the writer by the same rules, with the
same `tag`, so an observer who hears both has both ends.

A [first-contact frame](first-contact.md#what-an-observer-learns)
gives both ends in one frame: the first names the routing id it came
from, since nothing else tells the other end where to answer.

A [trace](#traces) names both ends too, for the same reason, and every
node on its way, each with how well it heard the one before; its answer
names them again. A trace tells an observer no routing id that
announces do not, but it tells which of the routes they offer a node
has selected, and that one node wanted to know the way to another. A
node that does not trace gives none of it. A leaf answers only a node
it shares a session with, so a stranger's trace to a leaf ends at the
relay that last had a route to it, and shows no more than announces
already do.

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
| This, 255 neighbours kept | 96.6%, 0.47 | 22.0%, 0.019 |
| This, 64 neighbours kept | 95.2%, 0.34 | 20.2%, 0.017 |

And in a town of 200 nodes at SF9, every node a relay: 100.0% with 255
neighbours kept and 99.9% with 64, against 21.0% for Meshtastic.

The nodes of this specification [listen first](#listening-first) as a
radio can; how that is modelled, and what it is worth, is below.

There is no broadcast in these runs, since this specification has none
yet, and the incumbents are built around it. The radio model's capture
and isolation figures are from the literature, not a bench.

**Why the source's wait does not wait for its hop.** A first version
let a message's first hop run out its retries, and another way, before
the message was tried again. A message that could not arrive then
stayed on the air for two minutes, and on the slow preset, where the
channel is full, 4.2% arrived in time; with the wait fixed, 14.4%, as
those runs then stood.

**Why a frame sent again waits a random time.** Two boards a foot
apart, each told to send the other a message at the same moment, sent
eight frames each and delivered neither: every wait in this section was
fixed, so both sent again together each time. The simulator does the
same with two nodes that send as soon as they have a frame, and frames
of one length. Messages delivered, of 400, and frames sent for each,
by `RETRY_JITTER`:

| `RETRY_JITTER` | SF9, 500 kHz | SF11, 250 kHz |
|---|---|---|
| 0 | 0%, 8.0 | 0%, 8.0 |
| 1 | 49%, 7.0 | 51%, 7.0 |
| 2 | 94%, 4.5 | 96%, 4.7 |
| 4 | 100%, 3.0 | 100%, 3.0 |
| 8 | 100%, 2.4 | 100%, 2.3 |
| 16 | 100%, 2.2 | 100%, 2.2 |

Four is the least that delivered every message. More costs fewer
frames and more time: on the 1000-node runs above, where few frames
meet this way, 4, 8 and 16 delivered what 0 did to within the seeds'
spread (96.7%, 96.7% and 96.6% against 96.7% on SF7), and the slowest
twentieth of messages took 11.5 s, 11.5 s and 13.1 s against 11.1 s.

The boards did not listen first then, and nor do the nodes of that
table. [Listening first](#listening-first) does not keep apart two
nodes that start within the time a radio takes to find a frame, so 0
still delivers nothing; but a node that listens holds its second try
for the other's, and with both listening 1 delivered every message, in
2.3 frames, and 4 in 2.2. Four is kept for the frames a radio does not
find.

**Why listen first, and why no longer than the frame.** On the
1000-node runs above, with the radio modelled as one is: a node knows
of a frame once its radio has been on it for five symbols and a
millisecond, and what it then sends is on the air a millisecond after
it looked. Messages in time, and for each second on the air, and the
median time a message took on SF7:

| | All on SF7, 125 kHz | Each on its own preset |
|---|---|---|
| Not listening | 95.9%, 0.36, 5.0 s | 12.7%, 0.013 |
| Listening | 96.6%, 0.47, 0.9 s | 22.0%, 0.019 |
| and a radio that finds a frame at once | 96.7%, 0.45, 0.9 s | 22.3%, 0.020 |
| and one that takes 12 symbols and 2 ms | 96.6%, 0.43, 1.0 s | 21.5%, 0.019 |
| and 5 ms from looking to sending | 96.5%, 0.48, 0.9 s | 21.5%, 0.019 |
| then a random wait up to 3 slots | 96.6%, 0.42, 1.0 s | 19.1%, 0.017 |
| then up to 15 slots | 96.6%, 0.41, 1.0 s | 15.1%, 0.014 |
| then up to 63 slots | 96.7%, 0.42, 1.1 s | 9.2%, 0.008 |

A slot is the time to find a frame and send: 7 ms on SF7, 22 ms on the
slow preset. A node that does not listen delivers nearly as much where
the channel has room, with a third more frames and five times the
wait, and little over half as much where it has none. How fast the
radio finds a frame matters little, within what a radio does. A random
wait after the frame, which a protocol whose nodes all answer the same
frame would need, costs time here and buys nothing: where the channel
is full, the wait is the minute a message has. With twenty nodes in one
room and a message from each every 15 s, a wait of up to 63 slots saved
a tenth of the frames and nothing else changed; every 5 s, which is
more than the channel holds, 46.6% arrived against 42.9%.

On two boards a foot apart, one given a message 10 to 60 ms after the
other, when the other's frame was on the air, 16 times: not listening,
the 16 messages each way took 43 and 42 frames, every pair having met;
listening, 19 and 19, and the boards waited 10 and 15 times.

An earlier draft's figures were from nodes that knew of a frame the
instant it began, as no radio does, and then waited 120 to 360 ms
before they looked again: 96.7% and 15.2% on these runs.

**Why an acknowledgement teaches nothing, and still ends a hop.** A
node on the way cannot tell an acknowledgement from a forgery, and as
first drafted one that ended a message's last hop was a sample of the
destination's floor. A forger could then turn a node down until it no
longer reached its neighbour. Taking nothing from acknowledgements
changed nothing measurable. On the 1000-node runs above, on SF7, with
the tables a board keeps (the simulator's
`scenarios/scale/region-core-fast.tsim` with that traffic, three
seeds), 98.9% of messages arrived in time against 99.1%, at 0.313 a
second on the air against 0.319, each within the seeds' spread (99.5%,
98.7% and 99.0% as it was). Relays that also went
on sending until they heard the frame passed on, and took no
acknowledgement as ending a hop but its last, did cost: 97.9%, at 0.265,
and a third more airtime passing frames on, since a relay often hears
the acknowledgement and not its neighbour. A node that can forge an
acknowledgement in earshot of a relay can as easily keep that relay
from hearing anything, and the source, which checks `proof`, is not
deceived. So a forged acknowledgement can cost a message a retry from
its source, and nothing more. A [worse sample](routing.md#links) from
one is not that first draft: it can turn a node up, never down, and a
forger can make it send louder, or route round a neighbour, which
jamming does as well.

**Why copies are answered so far and no further.** The same runs, with
a destination that answered no more than four acknowledgements of a
message and none after ten minutes, delivered what they did before
(99.0% and 0.318), and refused 20 copies a run. With two, 400 copies a
run were refused, and sources heard 1.4% fewer acknowledgements. On the
slow preset, where most of what is sent is lost, neither moved
anything beyond the seeds' spread.

**Why listen, and not acknowledge each hop.** The next node sends the
frame anyway. Hearing it costs nothing, and an acknowledgement for each
hop would double the frames.

**Why first contact's last hop is sent once.** A message's last hop is
ended by its acknowledgement, which the node before hears. The answer
to a first-contact frame carries another tag, which only the two ends
can compute, so the node before cannot know it for the answer; and
there may be no answer, from a node that refuses. Sending the last hop
three times for nothing would cost more than the frames it saved: the
node that began the handshake sends again anyway. An acknowledgement
for each hop was set aside for the reason above.

**Why `power` is in the head.** A node passing a frame on must be heard
by the node before it, which has turned its own power down to reach
only its neighbour. With no sender in the frame, the power it was sent
at and the strength it arrived with are all there is to reckon that
from.

**Why a trace, and why not authenticated.** Both incumbents give a
person the way a message went, as their public documentation has it:
Meshtastic's traceroute gathers the node numbers that pass it on, and
the signal-to-noise ratio at each, out and back; a
MeshCore direct message carries its repeaters' one-byte hashes in
every frame. Without one, a person whose message is slow can see only
that it is slow. This section puts nothing of the path in a message, so
a trace is a frame of its own, sent when a person asks. Entries could
be signed, by keys every relay announces, at 64 bytes a hop; the
signatures would show that each relay added its entry, and not that it
was the relay that passed the frame on, since any relay that heard the
trace could sign one. A trace is a diagnosis, and a forged one costs
whoever asked nothing but a wrong answer. Answering only a
session's other end was considered and set aside for relays: a person
traces a relay to find out whether it is the one that fails, and has
no session with it.

**Why a keeper and a relay with no route answer.** A message to a leaf
that sleeps waits with its keeper, and one to a destination a relay has
no route to dies there. Those are the two places a person most needs
to see, and a trace that went unanswered would show neither.

**Why an acknowledgement may go another way.** On the first field test
(v0.7.0-alpha.3, 2026-11-21) a leaf driven away from a relay sent it a
message through another relay, two hops, which arrived well. The relay
it was for still held the leaf as a neighbour up, from before it left,
and sent the
acknowledgement direct, by its selected route. It was lost, and the
leaf sent the message again. An acknowledgement's last hop is not
listened for, so the relay never knew, and an acknowledgement is not
sent another way when a hop is given up. The leaf had told the relay as
much: a source whose route to a neighbour goes direct sends direct, and
this one had routed round.

The route the acknowledgement takes instead may be infeasible, as the
route through another relay to a neighbour's leaf most often is. It
cannot loop. Only its first hop is chosen so; the relay passes it on by
its own selected route, and routes selected cannot loop. At worst that
route leads back to this node, which passes it on by its own selected
route, so it costs a few hops of one 19-byte frame, within `HOP_MAX`.
No table changes, so no route is drawn anywhere.

The head says nothing of the node a frame came from, and a field for it
would cost four bytes in every frame and be no more authenticated than
`hops` is. `hops` is enough to say that a relay passed the message on.
It is not authenticated either. A relay on the way that leaves `hops`
at `HOP_MAX` sends the acknowledgement by the selected route, as before.
A node that sends the message again with `hops` lowered sends a
[copy](#messages), which is acknowledged at most `COPY_ACKS` times
and for `COPY_TIME`, each now by a relay: the most it can cost is a
few acknowledgements' airtime over a longer way. Sending every
acknowledgement both ways would double what each costs to find what
one case needs; trying direct first and then another way needs a hop
listened for, which a last hop is not.

Measured in the simulator, the firmware's core over the field test as
a scenario (ternmesh/sim `scenarios/core/drive.tsim`, ten seeds, a
message each way every four minutes for 100 minutes), with this, the
next try another way and worse samples together, against the firmware
before them:

| | before | after |
|---|---|---|
| both ways at once: delivered, of 500 | 275 | 431 |
| both ways at once: given up by their sources | 407 | 122 |
| from the leaf alone: delivered, of 250 | 228 | 236 |
| from the leaf alone: given up though delivered | 182 | 81 |
| to the leaf alone: delivered, of 250 | 47 | 89 |

**Why a source's next try avoids its last first hop.** A source waits
`ACK_WAIT` plus a few journeys for its acknowledgement, some five
seconds on a route of one link, and a hop is given up only after its
third send, `HOP_WAIT` apart, some twelve. So the source starts again
before any hop of its own is given up, and [another
way](#hops), which follows a hop given up, never comes: each try went
to the same neighbour, twice, as long as the route lasted. A route that
lasts is what a stale link is. On the field test the relay at the desk
sent everything for a leaf that had driven away direct, try after try.

The next try goes elsewhere only when nothing of the last was heard at
its first hop. A message passed on there whose acknowledgement was lost
further on tries the same way again, and a first hop that has truly
gone soon shows it: two sends unheard in each try. The route taken
instead may be infeasible, as the route through another relay to a
relay's own leaf most often is. As for an acknowledgement (above), only
the first hop is chosen so, and the relays pass it on by their selected
routes, which cannot loop; at worst it reaches the source again, which
holds the same frame and ignores it, and the try is lost. As first written the next try avoided the last neighbour and
nothing else changed, and in the simulator's drive that did harm: with
tries alternating between two neighbours, no neighbour was ever sent
the message more than `HOP_RETRIES` times, so no hop was ever counted
given up, no boost rose, and a leaf never reached `SOLICIT_HOPS` at the
relay it had left, so never solicited, which is what had mended its
floor for the relay it now needed. So a try unheard is a hop given up.
Forgetting still takes `DEAD_HOPS` of them, with nothing heard between.

Measured as first written, the next try took the lowest metric of the
other routes, and in four seeds of ten the relay at the desk never
reached the leaf. It still held routes to the leaf through the relays on
the hill, learnt while everyone was in one house, through links it had
not heard since and still held up; they tied on metric with the route
through the relay that could reach the leaf, and came first. Tries then
went back and forth between the leaf and a relay on the hill, and never
by the one that worked. A neighbour that frames have been lost to since
it was last heard is the one a stale link leads to, so a route round
prefers the others; that counter is kept for `DEAD_HOPS` already. And
once the desk had given `DEAD_HOPS` hops up at the leaf and forgotten it,
it held no route it might select and only asked, though the route
through the patio was still there: so a source with no route sends by
its route round no neighbour while it asks.

**Why 24 hops given up, and not 3.** In the simulator, forgetting a
neighbour sooner delivered less with every node up and less with a
quarter of the relays going down and coming back: at 3, 6 and 12 hops
it was worse at each step than at 24. The false alarms outweigh the
dead found sooner.

## Not yet measured

* **Any of the parameters, on radios**, but that `RETRY_JITTER` 0 fails
  on two, and that two which listen first keep their frames apart.
* **How often a node hears its neighbour pass a frame on**, on real
  links: the next hop may be heard and its own next hop not.
* **Memory**: each frame in hand is a whole frame and some thirty bytes.
* **How long a radio takes to find a frame**, and how often it finds a
  preamble where there is none.
* **First contact across a relay**, in the simulator or on radios: how
  often a handshake completes, with its last hops sent once.
* **Traces**, in the simulator or on radios: how often one is answered
  where a message would be delivered, and whether `TRACE_ENTRIES` and
  `TRACE_ANSWERS` are what a mesh needs.

## Not yet specified

* **Routing ids that change** ([above](#what-an-observer-learns)).
* **A flood when the routes are stale.** The simulator floods a message
  given up at a leaf that has moved, through relays, a few hops. It
  would be [a flood](flooding.md) of a kind not yet defined.
* **Sharing a full channel.** The [airtime budget](airtime.md) bounds
  what each node sends, not what a mesh's nodes send together where
  the channel is full.
* **Frames for every node** are [their own section](flooding.md), and
  follow no route.
* **First-contact answers the way the frame came.** A handshake's
  answer to a source that routed round a stale direct link meets what
  an acknowledgement met on the field test; it is sent another way
  when its hop is given up, but only by a feasible route, and its last
  hop is not listened for.
* **Fragments**: a message is one frame.
* **Priority** between messages.
