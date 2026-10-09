# Frames for every node

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). The flood is how
the simulator ([ternmesh/sim](https://github.com/ternmesh/sim),
candidate 3) carries a broadcast, written down, and has since been run
there through the firmware's own code. The
[allowance](#the-allowance) is not from the simulator's candidate; what
it does and does not do there is [below](#what-was-measured). Every
number here is **provisional**.

[Frames that follow routes](forwarding.md) carries a frame to one node.
This section carries a frame to every node within a few relays of where
it began: a **flood**. Each relay that hears the frame sends it once
more, unless it hears that others already have. What is flooded is for
the section that defines the frame to say; the one kind so far is a
[group's message](groups.md).

Test vectors: [`vectors/flooding.json`](../vectors/flooding.json),
produced by
[`vectors/tools/flooding.py`](../vectors/tools/flooding.py).

## Goals

1. **A flood costs a frame a relay at most, and where relays are many,
   far less.** A relay that hears another pass the frame on does not.
2. **A flood stops.** It goes a few relays from where it began, and no
   node sends one frame twice.
3. **No sender, no destination.** What this section puts in a frame
   names no node.
4. **Floods do not take the channel.** A node spends a bounded share of
   its time on its own floods and another on other nodes', whoever asks.

## Notation

As in [Frames that follow routes](forwarding.md): a **relay** forwards
other nodes' frames and a **leaf** does not, and the **airtime** of a
frame is its time on air under the profile in use
([Radio settings](phy.md)). A relay's **relay neighbours** are the
neighbours it [may use](routing.md#roles) that are relays: those whose
link is up.

## The head

Every flooded frame starts with three bytes:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `hdr` | the frame's type |
| 1 | 1 | `hops` | below |
| 2 | 1 | `power` | what this frame was sent at, `i8` dBm, rounded up |
| 3 | | | as the type gives |

`hops` and `power` change at every node. Nothing after them does.

One kind of frame is defined:

| `hdr` | Frame | After the head |
|---|---|---|
| `0x60` | a **group frame** | [Groups](groups.md#the-frame): at least 24 bytes |

A receiver MUST discard a group frame shorter than 27 bytes, and MUST
NOT treat a frame whose `hdr` is none of this table's as flooded.

**A frame's id** is how a node tells a frame it has had from one it has
not:

```
id = SHA-256(frame[3..])[0..8]
```

every byte after the head, so the same for every copy of a frame
wherever it was heard, and different for any other frame.

## Sending

A node floods a frame of its own with `hops` set to `FLOOD_HOPS` and
`power` to what it is sent at, once. It takes the frame's id as
[seen](#receiving) before it sends, and waits for
[its allowance](#the-allowance).

**How loud.** A flooded frame, a node's own or one it passes on, goes
at the highest of:

* what a frame for every neighbour goes at
  ([Routes](routing.md#power-for-every-neighbour)); and
* for every relay neighbour that one of the node's
  [selected routes](routing.md#selecting-a-route) goes through, that
  neighbour's floor plus `POWER_MARGIN`, rounded up to a whole dBm.

It is kept between the node's lowest power and its full power, and is
full power if any such neighbour's floor is not known. A neighbour's
boost plays no part.

[Listening first](forwarding.md#listening-first) holds for flooded
frames as for every other.

## Receiving

A node that receives a flooded frame works out its id.

**A frame it has seen** is a copy. If the node is
[waiting to pass that frame on](#passing-on), the copy counts against
it. Otherwise the copy is ignored.

**A frame it has not seen** is taken as seen, and handed to the section
that defines its kind: every node does this, leaf or relay, whatever
`hops` says. A relay then [passes it on](#passing-on), or not.

A node MUST treat a frame as seen for `SEEN_FOR` after it first
received or sent it, and MAY forget it sooner only once it has taken
`SEEN_ROOM` others as seen since.

## Passing on

A leaf MUST NOT pass a flooded frame on. A relay passes on a frame it
had not seen as follows.

1. It reads `hops` as no more than `FLOOD_HOPS`: a frame that says more
   is taken to say `FLOOD_HOPS`.
2. A relay with more than `FLOOD_SPARSE` relay neighbours is **in a
   crowd**. It MUST NOT pass on a frame whose `hops` is 0 or 1, and
   passes any other on with `hops` one less.
3. A relay with `FLOOD_SPARSE` relay neighbours or fewer is **a
   bridge**. It MUST NOT pass on a frame whose `hops` is 0, and passes
   any other on with `hops` unchanged.
4. It waits a random time, uniform up to `FLOOD_WAIT` airtimes of the
   frame, before the frame is offered to the radio.
5. If, before its own copy is on the air, it has received
   `FLOOD_COPIES` copies of the frame, the first included, it MUST drop
   the frame and not send it.
6. When the wait ends, the frame is sent if
   [the allowance](#the-allowance) can pay for it, and dropped if not.

A relay sends a frame it passes on once. Nothing listens for it and
nothing answers it.

## The allowance

A node keeps two token buckets for flooded frames, each as
[Routes' cap](routing.md#the-cap) is: one for its own, which fills at
`FLOOD_OWN` of the node's time and holds `FLOOD_OWN_WINDOW` of that,
and one for those it passes on, which fills at `FLOOD_RELAY` and holds
`FLOOD_RELAY_WINDOW` of that. Either holds one 255-byte frame if that
is more, and starts full. A frame is charged its airtime when it is
sent.

* A node's own frame waits until the first bucket holds its airtime. A
  node MUST NOT send it sooner.
* A frame to be passed on whose airtime the second bucket does not hold
  when its wait ends MUST be dropped.

This is beside what a [profile](phy.md#profiles) allows a node to
transmit at all, which bounds these and everything else it sends.

## Parameters

| Name | Value | |
|---|---|---|
| `FLOOD_HOPS` | 5 | so four relays in a crowd pass a frame on along any path |
| `FLOOD_SPARSE` | 8 | relay neighbours, at most, of a bridge |
| `FLOOD_WAIT` | 8 | airtimes |
| `FLOOD_COPIES` | 2 | so one more copy heard drops a waiting frame |
| `SEEN_FOR` | 60 s | |
| `SEEN_ROOM` | 128 | frames |
| `FLOOD_OWN` | 0.5% | of a node's time |
| `FLOOD_OWN_WINDOW` | 600 s | |
| `FLOOD_RELAY` | 3% | of a node's time |
| `FLOOD_RELAY_WINDOW` | 60 s | |
| `POWER_MARGIN` | 10 dB | as in Routes |

## Conformance

An implementation conforms to this section if, for
[`vectors/flooding.json`](../vectors/flooding.json):

* **heads:** it builds `frame` from `hdr`, `hops`, `power` and `rest`,
  and reads them from `frame`, and finds the frame's `id`;
* **rejected:** it does not take `frame` as a flooded frame;
* **same:** it finds the frames `a` and `b` to be copies of one frame,
  or not, as `same` says;
* **passes:** as a node of the `role` given with `relay_neighbours`
  relay neighbours, receiving a frame it has not seen whose `hops` is
  `hops`, it passes the frame on with `sends` as its `hops`, or, where
  `sends` is `null`, does not;
* **copies:** as a relay waiting to pass a frame on, having received
  `received` copies of it in all, the first included, it drops the
  frame, or not, as `drops` says;
* **waits:** passing on a frame of `length` bytes at
  `spreading_factor` and `bandwidth_hz`, it first waits no longer than
  `longest_ns`, and not the same time for every frame;
* **powers:** with `every` what Routes gives for a frame for every
  neighbour, `floors_sixteenths` the floors of the relay neighbours its
  selected routes go through (`null` for one not known), and
  `lowest` and `full` its lowest and full power, it sends a flooded
  frame at `power`;
* **seen:** taking each id of `takes` as seen at its `at_ns`, it finds
  at each time in `asks` that `id` is seen, or that it may be forgotten,
  as `seen` says: `true` where it MUST be seen;
* **allowances:** with a bucket that fills at `share_ppm` millionths of
  the node's time and holds `window_s` seconds of that, at
  `spreading_factor` and `bandwidth_hz`, full at time 0, offered each
  frame of `frames` in order, of `airtime_ns` at `at_ns`, it finds the
  bucket holds the frame's airtime, or not, as `pays` says. A frame
  paid for is sent and charged then; one that is not is not sent.

When frames go depends on random times and on what is heard. That a
flood reaches the nodes it should is checked by running implementations
against each other and against the simulator.

## What an observer learns

Nothing in the head names a node. An observer learns that a frame is a
flood, how long it is, and from `hops` roughly how far it has come: a
frame whose `hops` is `FLOOD_HOPS` was sent by the node it began at, or
by a bridge next to it, so an observer in earshot of a writer can tell
which transmitter the writing came from, as it can for any radio. It
learns nothing that joins one flood to another, unless the frame's kind
gives it: a [group frame](groups.md#what-an-observer-learns) does not.

## Rationale

**A flood, and not routes to every member.** A frame that is for many
nodes, some of them unknown to its writer, has no route to follow. The
alternative that keeps to routes is a copy sent to each reader in turn,
which costs a message's whole path once a reader. A flood costs the
same whoever is listening.

**Hear before repeating.** A relay in a crowd is one of many that heard
the frame, and most of their copies would reach no node the first did
not. A relay waits, and stays silent if it hears one more copy. The
wait is long, eight airtimes where a frame that follows a route waits
two, because the wait is what lets a copy be heard: with three, the
simulator's relays heard fewer copies in time and sent more.

**Bridges spend no hop.** Where relays are few, a flood costs a frame a
relay and no more, and a hop limit that suits a crowd stops it short.
At −5 dBm on the simulator's fast preset, where a node has five links,
four relay hops reached 11.6% of nodes; with relays that have eight
relay neighbours or fewer spending none, 39.0%. Sixteen hops for every
relay did as much there, 37.7%, and cost 13% of the deliveries per
second of airtime at 20 dBm, where relays are many. A flood along a long line of bridges does go the whole line:
each still sends it once.

**As loud as the relay tier needs.** A flooded frame first went as an
announce does, loud enough for the eight nearest neighbours. With the
radio at high power those are leaves next door: a relay's copy reached
no other relay and the flood died in a hop or two, 5,514 deliveries in
the simulator's region against 85,505 with every link known. Reaching
every relay a route goes through keeps the relays joined for floods as
routing sees them joined. The simulator reached the neighbours its
routes *to relays* went through; a node here is not told which far
nodes are relays, so it reaches every relay it routes through, which is
those and now and then one more.

**What it costs.** The channel is one. In the simulator's deployed
region, floods at that power took unicast messages on time from
29.0–41.3% to 24.6–31.6%, and broadcast from 1.1–16.3% to 11.7–34.9%.
A mesh whose broadcasts reach one node in ten is no use for the group
conversations most of its traffic is.

**An allowance, and two.** Field reports of other meshes put public
floods, not private messages, at the root of channels that stopped
working. A relay cannot tell a group's frame from noise made to look
like one, so anyone can ask every relay in reach for a frame of
airtime. The second bucket bounds what that costs each relay, and
keeping it apart from the first means a relay spent on others' floods
can still send its own.

**What the allowance is not.** It does not keep a mesh's broadcasts
within what the channel holds. Each node is far inside its own bucket
when the mesh as a whole is past it: see
[What was measured](#what-was-measured). What would is a share of the
air divided between nodes, which is
[not yet specified](forwarding.md#not-yet-specified), or floods that do
not go everywhere.

**An id from the bytes.** A flood's id could be a field its writer
fills. A node that heard a frame could then send rubbish under the same
id and have relays take the real one as a copy. A hash of the frame
cannot be made to match.

## What was measured

The firmware's flood (ternmesh/firmware, `tern/flood.h`), run in the
simulator in place of candidate 3's: a thousand nodes, three seeds, a
message from every node every 30 minutes, a quarter of them
broadcasts. Broadcast destinations reached within a minute, at −5, 0,
5, 10 and 20 dBm, which stand for how many nodes each one hears, from
5 to 284:

| | Candidate 3 | The firmware |
|---|---|---|
| SF7, 200 relays | 39.9, 66.9, 77.5, 87.1, 90.2% | 39.1, 65.8, 78.0, 83.2, 84.8% |
| SF8 at 62.5 kHz, 200 relays, the channel full | 20.8, 23.3, 26.3, 22.5, 5.7% | 20.2, 27.5, 32.1, 31.7, 17.9% |
| SF9, every node a relay | 27.2, 31.8, 35.2, 34.5, 25.7% | 27.3, 33.6, 38.4, 42.5, 45.3% |

The two differ in more than the flood: the firmware listens before it
sends, and candidate 3 ran over another MAC. Given candidate 3's, the
firmware's flood reaches 88.4% and 89.5% in the first row at 10 and
20 dBm, which is candidate 3's to within a seed's spread. So the flood
here is the one that was measured before it was written down.

**The parameters, each changed alone**, in the first row at 10 and
20 dBm, where the defaults reach 83.2% and 84.8%:

| | Reached | Deliveries per second of airtime, against 56.7 and 50.0 |
|---|---|---|
| `FLOOD_COPIES` never | 78.8, 79.7% | 33.6, 31.4 |
| `FLOOD_COPIES` 3 | 81.0, 80.9% | 40.1, 35.1 |
| `FLOOD_WAIT` 3 | 75.0, 78.0% | 45.0, 40.0 |
| `FLOOD_HOPS` 8 | 84.7, 85.1% | 48.6, 43.7 |
| `FLOOD_SPARSE` 16 | 85.6, 85.6% | 52.3, 45.1 |

A relay that stays silent on one more copy reaches more nodes than one
that always sends, on three fifths of the airtime.

**The wait, longer.** The 4 to 5 points the firmware is short of
candidate 3 in the first row at 10 and 20 dBm are not from listening
first. The MAC candidate 3 ran over holds a frame a random time of its
own before sending it, and a relay held longer hears more copies. A
longer `FLOOD_WAIT` does the same, on less airtime. Unicast messages
and broadcast destinations on time at the five powers, and at 0 and
20 dBm the time within which 95% of the broadcasts that arrived did:

| | `FLOOD_WAIT` | Unicast | Broadcast | 95% within |
|---|---|---|---|---|
| SF7, 200 relays | 8 | 60.8, 92.0, 98.9, 98.0, 96.1% | 39.1, 65.8, 78.0, 83.2, 84.8% | 5.8 s, 2.8 s |
| | 16 | 60.7, 90.5, 98.2, 97.9, 96.1% | 39.2, 66.8, 78.7, 88.2, 88.7% | |
| | 24 | 60.7, 90.6, 98.6, 98.0, 96.1% | 39.1, 66.4, 79.3, 88.3, 90.3% | 13.7 s, 3.8 s |
| SF8 at 62.5 kHz, the channel full | 8 | 21.1, 23.2, 20.0, 17.7, 21.1% | 20.2, 27.5, 32.1, 31.7, 17.9% | 26.0 s, 30.3 s |
| | 16 | 20.9, 22.5, 17.9, 16.9, 19.5% | 17.6, 28.4, 34.8, 31.9, 19.2% | 43.7 s, 50.5 s |
| | 24 | 20.1, 22.1, 18.1, 17.3, 19.5% | 14.2, 27.4, 32.3, 30.3, 18.2% | 62.1 s, 69.4 s |
| SF9, every node a relay | 8 | 38.2, 40.5, 36.8, 38.7, 34.6% | 27.3, 33.6, 38.4, 42.5, 45.3% | 11.5 s, 12.0 s |
| | 16 | 35.4, 34.3, 30.1, 29.3, 23.8% | 28.7, 37.5, 44.7, 49.0, 49.7% | 18.4 s, 19.3 s |
| | 24 | 34.0, 32.4, 28.5, 27.1, 20.2% | 28.6, 38.9, 47.0, 52.3, 51.5% | 25.6 s, 26.0 s |

Where the channel has room, sixteen airtimes reach more for the delay
alone. Where it has none, the floods that now get through take
unicast's share, or arrive late. `FLOOD_WAIT` stays at 8 until
something says which of the two a relay sends first.

**The allowance.** At that traffic it does nothing: without it, the
first row is the same to the digit. With a message from every node
every 5 minutes, three quarters of them broadcasts, the relays' bucket
binds only where relays are few. At 0 dBm in the first row, unicast
messages on time are 28.0% with it and 16.6% without, and broadcast
14.2% against 16.5%; at 10 and 20 dBm, and with the channel full,
there is nothing in it either way.

That load is more than the channel holds, allowance or none: unicast
on time falls from 92.0, 98.0 and 96.1% to 28.0, 23.6 and 39.2%. No
node is near its own bucket. A thousand of them, each allowed 0.5% of
its time, are together allowed five channels.

## Not yet measured

* **A longer `FLOOD_WAIT` with a rule for which goes first**, a
  flooded frame or one that follows a route.
* **The allowance's numbers against each other.** One load was run
  with them and without. Whether 3% is the right share for a relay,
  or 0.5% for a writer, was not asked.
* **A workload with groups in it**, drawn from what meshes carry in the
  field: here every broadcast is for every node.
* **Any of it on radios**, past one hop between two boards.

## Not yet specified

* **A flood that is scoped**, by place or by a region code, and not
  only by hops.
* **A flood when routes are stale**, for a message given up at a leaf
  that has moved ([Frames that follow routes](forwarding.md#not-yet-specified)).
* **Priority** between flooded frames, and between them and frames that
  follow routes, beyond the two buckets.
* **Announces of a node to every other**, such as its name: nothing
  here is sent unasked.
