# Presence cards

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It has not yet been
reviewed by a cryptographer, and it must be before it is frozen. What
it costs was measured in the simulator before it was written:
[What was measured](#what-was-measured). Every number here is
**provisional**.

Tern has no public channel: a [group](groups.md) is those who were
invited. That leaves a person with a new node nobody to talk to until
somebody hands them an address [off the air](sharing.md). A **card** is
how a node that chooses to says, to the nodes near it, who it is: its
address and a name. Someone browsing who is about sees the card, and
can make [first contact](first-contact.md) from it. What is said after
that goes over a session, as anything else does.

A card is a [flood](flooding.md) that goes a short way, rarely, and
only from nodes whose users have turned cards on.

Test vectors: [`vectors/cards.json`](../vectors/cards.json), produced
by [`vectors/tools/cards.py`](../vectors/tools/cards.py).

## Goals

1. **A way to meet people that is not a channel.** A card says who is
   about; it carries no conversation. Talking is a session, which costs
   only the two who talk.
2. **Off until a user turns it on.** A node that has not been told to
   send cards sends none, and the rest of the protocol is as private as
   it was.
3. **Local and rare.** A card starts with two hops, so that in a crowd
   one relay passes it on, and a node sends one every two hours. What
   cards cost the mesh grows with how many nodes send them and not with
   what anyone says.
4. **A card cannot be forged.** It is signed with the key behind the
   address it carries, so whoever shows a card's name beside an address
   knows the holder of that key chose it.
5. **One frame.** At most 134 bytes, with a name of up to 31.

What this does **not** give, and a reader should know before the rest:

* **A name is a claim.** The signature proves that whoever holds the
  address chose the name, not that the name is true. Two cards can
  carry one name.
* **A card puts its sender's address in clear.** Every other frame
  keeps it out ([first contact](first-contact.md#goals), goal 2). A
  node sending cards can be recognised by anyone in earshot, every time
  it sends one: that is what turning cards on is.
* **Nothing stops a flood of cards from new keys.** Anyone can make an
  address. The [allowance](flooding.md#the-allowance) bounds what any
  one transmitter costs each relay, as for every flood.

## Notation

As in [Groups](groups.md#notation). `Sign(sk, M)` is Ed25519 (RFC 8032,
section 5.1.6) of the message `M` under the node's key, whose public key
is its [address](first-contact.md#addresses); `Verify(A, M, sig)` is
its check (section 5.1.7). Fields are big-endian.

## The frame

| Offset | Bytes | Field | Signed |
|---|---|---|---|
| 0 | 1 | `hdr` | yes |
| 1 | 2 | `hops`, `power`: for the [flood](flooding.md#the-head) | no |
| 3 | 32 | `address`: the sender's [address](first-contact.md#addresses) | yes |
| 35 | 4 | `number`: `u32`, higher for each card the node sends | yes |
| 39 | `n` | `name`: UTF-8, 0 to 31 bytes | yes |
| 39 + `n` | 64 | `sig` | |

`hdr` is `0x68`: format `01`, draft 0; type `101`, a card; flags
`000`, none defined. The frame is `103 + n` bytes.

```
M    = "tern v0 card" || hdr || address || number || name
sig  = Sign(sk, M)
```

`hops` and `power` are left out of `M`: every relay changes them.

The [flood's table of kinds](flooding.md#the-head) gains a row:

| `hdr` | Frame | After the head |
|---|---|---|
| `0x68` | a **card** | this section: 100 to 131 bytes |

## Sending

A node MUST NOT send a card unless its user has turned cards on, and
MUST stop when they turn them off. Turning cards on is a setting of
the node's, which the [companion link](companion.md#cards) carries
with the name, and by which a client is told of the cards the node
holds.

1. `number` MUST be higher than that of any card the node has sent
   before with this address. A node MAY use a count kept in flash, or
   the time in seconds where it knows it.
2. `name` is what the user chose to be shown as. A node MUST NOT put
   any other name in it, and SHOULD send none rather than invent one.
3. The frame is [flooded](flooding.md#sending), but with `hops` set to
   `CARD_HOPS` and not `FLOOD_HOPS`, and paid for from the allowance
   for the node's own floods.

A node sends its first card when cards are turned on, and each next
one between `CARD_EVERY / 2` and `3 × CARD_EVERY / 2` after the last,
drawn uniformly, so that nodes turned on together do not stay in step.
It MAY send one sooner after its name changes, but not twice within
`CARD_EVERY / 2`. Turning cards off and on again does not start that
over: a node that sent a card less than `CARD_EVERY / 2` before cards
are turned on again sends its first `CARD_EVERY / 2` after that one,
so that no client, by toggling them, makes it send more often.

## Receiving

A node holds, for each address it has a card from, the highest
`number` it has accepted and what that card said. To receive a card,
which [the flood](flooding.md#receiving) hands over once however many
copies arrive:

1. A node MUST discard a card shorter than 103 bytes or longer than
   134, or whose `hdr` is not `0x68`.
2. It MUST discard a card whose `address` is its own, or is not a
   valid address as [First contact](first-contact.md#addresses) says,
   or whose `name` is not valid UTF-8. This comes before the signature:
   an address of small order, with a signature to match, passes
   Ed25519's equation for any message.
3. It MUST discard a card unless `Verify(address, M, sig)` passes.
4. It MUST discard a card whose `number` is not higher than the one it
   holds for that address. Otherwise it holds this one in its place.

A node MAY forget cards, and SHOULD forget those it has not heard again
in `CARD_KEPT`, oldest first when it has no room. Forgetting a card
forgets its number, so an old card heard again after that is new to it:
see [Not yet specified](#not-yet-specified).

What a node does with a card it holds is its user's to see, as **who is
about**: the name, beside the address's [short code](sharing.md), and
how recently it was heard. A client is told of them as the [companion
protocol](companion.md#cards) says. A node MUST NOT save a card's sender as a
contact, or start first contact with it, unless its user says so.

A card does not need to be held to be passed on, and whether it is
passed on is [the flood's](flooding.md#passing-on) to say, but for one
rule: a relay MUST read a card's `hops` as no more than `CARD_HOPS`,
as it reads every flood's as no more than `FLOOD_HOPS`. A relay
SHOULD NOT pass on a card it discarded at step 3 or 4.

## Parameters

| Name | Value | |
|---|---|---|
| `CARD_HOPS` | 2 | what a card's flood starts with |
| `CARD_EVERY` | 2 h | between one node's cards, on average |
| `CARD_KEPT` | 24 h | a card not heard again for this long is forgotten |

## Conformance

An implementation conforms to this section if, for
[`vectors/cards.json`](../vectors/cards.json):

* **accepted:** given `seed`, `number`, `name`, `hops` and `power`, it
  produces exactly `frame`, signing `signed`; and, as a node whose
  address is `self`, it accepts `frame` and reads `address`, `number`
  and `name` from it;
* **rejected:** as a node whose address is `self`, it discards each
  `frame`;
* **relayed_still_valid:** as a node whose address is `self`, it
  accepts it: a card with its `hops` and `power` changed, as a relay
  changes them;
* **deliveries:** as a node whose address is `self`, holding no cards,
  given each `frame` in order, it holds the card of exactly those whose
  `keep` is true.

That a node sends no card until its user turns cards on, and how often
it sends them, cannot be checked by vectors. They are requirements
nonetheless, checked by reviewing an implementation.

## What an observer learns

Everything in a card: the sender's address, the name it chose, and its
number. An observer who hears a node's cards can tell that the same
node sent them, wherever it is heard, for as long as the node keeps
its address. Where `number` is the time, it also learns the sender's
clock.

That is the purpose of a card, and why a node sends none until its
user turns them on. A user who wants to be found by some people and not
others has [sharing](sharing.md) instead, which puts nothing on the
air.

What a card does **not** tell an observer is who the node talks to:
its sessions and its groups' frames look as they did.

## Rationale

**A card, and not a public channel.** A channel every node holds the
key to is the one thing in a mesh whose cost no one bounds: it grows
with how much people say. Field reports of other meshes put public
floods at the root of channels that stopped working
([Frames for every node](flooding.md#rationale)), and in the simulator
a public room where each node said one line every fifteen minutes took
group messages from 18.8% of their destinations to 5.8%
([below](#what-was-measured)). Every member of a shared-key group can
also write as any other ([Groups](groups.md#goals)), which among
strangers means anyone can be anyone. A card is the part of a public
channel that makes meeting people possible, without the part that
costs: a node says who it is, at a rate the protocol sets, and the
conversation moves to a session.

**Short, not far.** A card flooded as far as a group's frame,
`FLOOD_HOPS`, every hour from every node, cost more than a quiet public
room did: group messages at 10.7% of their destinations against the
room's 14.3%. What makes cards cheap is the hop count. Two hops took
the cost to under half of that; with a card every two hours it fell to
2.4 points, and with one hop to within the runs' noise. Who is about is
a local question, and a card that answers it further away is airtime
spent on people too far to meet.

**Two hops, not one.** One hop is cheaper, but a card at one hop
reaches only the nodes its sender's own frame reaches, and
[a flood goes only as loud as the relays need](flooding.md#sending):
in the simulator's sparser map, a node saw half as many cards at one
hop as at two. Two let a card cross the relay a sender is next to.

**Every two hours.** Halving the rate took a third off the cost, and a
card already held is shown for `CARD_KEPT`: someone browsing sees
everyone who sent a card in the last day, not only the last hour.

**Signed.** A signature is 64 bytes of a card's 103 to 134, and a card
without one cost a little less: 12.3% of group destinations reached
against 10.7%, at the full rate and `FLOOD_HOPS`. Without it anyone
could send a card with another node's address and a name of their
choosing, and the person who made first contact from it would reach
the real node, under a name it never chose. The signature is what
makes the name the address holder's, and a relay that checks it passes
no forgery on.

**The address in clear.** A card exists to be found, and a receiver
needs the address to make first contact. A routing id, four bytes,
would name the node only to those who knew its address already.

**A number, not a time.** Most nodes do not know the time. A number
that only rises lets a receiver keep the newest card from each node and
refuse an older one, which is what stops a recorded card from bringing
back an old name. A node that knows the time can use it as the number.

**Off by default.** Turning cards on gives up what [What an observer
learns](#what-an-observer-learns) says. It is the user's to give up.

## What was measured

The simulator ([ternmesh/sim](https://github.com/ternmesh/sim),
`tools/cards.py`, over `scenarios/scale/region-core-cards.tsim`) ran
the firmware's own routing and flood on its 1000-node region, on the
deployed preset with 200 relays, with the region's usual load: a
message from each node every 30 minutes, a quarter of them to a group.
On top of that load it ran cards, and for comparison a public room.
Each row is the mean of three seeds, with the spread between them;
**unicast** and **group** are the shares of messages, and of a group
message's destinations, reached on time; **seen** is the cards a node
received in the hour, on average.

The simulator's `routing.card_hops` stands in for `CARD_HOPS`, which
the firmware does not have yet: it sets what a card's flood starts
with, and nothing else. A card is a 123-byte frame, a name of 20 bytes;
a room's line is 67.

At 5 dBm, 15 dB below the deployed power, where a node has about 75
links:

| On top of the load | Unicast | Group | Seen |
|---|---|---|---|
| nothing | 31.4 ± 0.8% | 18.8 ± 0.6% | |
| a card an hour, `FLOOD_HOPS` | 24.3 ± 0.7% | 10.7 ± 1.2% | 75.0 |
| the same, unsigned (59 bytes) | 25.2 ± 0.4% | 12.3 ± 0.6% | 118.3 |
| three cards an hour, `FLOOD_HOPS` | 18.4 ± 0.3% | 6.2 ± 0.4% | 134.8 |
| a card an hour, 2 hops | 26.8 ± 0.8% | 15.2 ± 0.8% | 49.9 |
| a card an hour, 1 hop | 29.4 ± 0.0% | 16.5 ± 1.1% | 24.7 |
| **a card every 2 hours, 2 hops** | **28.4 ± 0.5%** | **16.4 ± 1.0%** | **26.3** |
| a card every 2 hours, 1 hop | 29.1 ± 0.4% | 18.1 ± 1.3% | 13.5 |
| a quarter of nodes, a card an hour, 2 hops | 29.6 ± 0.6% | 17.7 ± 0.8% | 12.4 |
| a public room, a line every 2 hours | 27.1 ± 0.9% | 14.3 ± 0.4% | 68.6 |
| a public room, a line every 15 minutes | 18.0 ± 0.2% | 5.8 ± 0.4% | 231.7 |

At the deployed 20 dBm, where a node has about 490 links, every
change but three cards an hour and the busy room was within two
points of the load alone, and most within the noise. There the
channel's own crowd costs more than anything sent on top of it.

What these say:

* **Every node sending cards costs something,** whatever the settings.
  The parameters here, every node sending, cost group messages 2.4
  points and unicasts 3.0. Cards are opt-in, and a quarter of nodes
  sending, at twice this rate, cost 1.1 and 1.8.
* **A card costs about what a quiet public room costs,** line for
  line, and a public room has no rate but what people say. The room
  that cost 13 points was each node saying a line every quarter hour,
  which is not much for a chat.
* **The cost is the number of cards and how far they go,** more than
  their size: of the 8.1 points hourly cards cost group messages at
  `FLOOD_HOPS`, dropping the signature saved 1.6, and two hops 4.5.

The load alone reaches few destinations in this region: what was
measured is what cards take from what the mesh delivers now, not what
it should deliver.

## Not yet specified

* **Where a node is.** A card could carry a [cell](positions.md) as
  coarse as the user chooses, so that who is about can say roughly
  where. It costs a few bytes and gives away more than a name does.
* **More than a name**: a line about the sender, or what they are about
  for. The frame has room for 120 more bytes; each one is airtime.
* **Replay of a forgotten card.** A card recorded and flooded again
  once its receivers have forgotten its number is taken as new, saying
  what it said then. It cannot say anything its sender did not.
* **Sending a card on asking.** A node that has just been turned on
  could ask those near it for theirs, rather than wait up to an hour.
