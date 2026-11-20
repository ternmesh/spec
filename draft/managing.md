# Managing a node over the mesh

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Every number here
is **provisional**, and none has been measured on radios.

A relay does its work where people are not: on a mast, a roof, a hill.
Its owner sets it up over a cable or Bluetooth, through the
[companion protocol](companion.md), and after that can reach it only by
going back to it. This section lets the node's **owners** drive it over
the mesh, from their own node, with the requests of the companion
protocol they already use: see how it is, change its settings, choose
who it takes, and restart it.

Nothing new is needed on the air but two kinds of
[message for the node](unicast-security.md#the-frame). A request goes
in a [session](first-contact.md) between the owner's node and the node
it manages, so it is sealed, proves who sent it, and cannot be played
again; a node acts only for those it holds as owners, and tells anyone
else, at once, that they are not one.

Test vectors: [`vectors/managing.json`](../vectors/managing.json),
produced by [`vectors/tools/managing.py`](../vectors/tools/managing.py).

## Goals

1. **No trip to the mast.** What an owner can do over a cable to keep
   a relay working, short of new firmware, they can do over the mesh.
2. **Only its owners.** Who may manage a node is a list of addresses,
   each proved by its session. No password crosses the air, nor is
   kept to be guessed.
3. **Hard to cut off.** A setting changed over the mesh that leaves
   the node out of its owners' reach goes back by itself.
4. **One protocol.** The requests, answers and news are the companion
   protocol's, so a client that drives its own node can drive another
   with the code it has.
5. **Cheap.** Nothing is sent unasked, and an answer packs as much as
   fits in one frame.

## Notation

As in [Companion](companion.md#notation) and
[Secured unicast frames](unicast-security.md#notation). The values
this section names in `CAPITALS` are in [Parameters](#parameters). The
**manager** is the owner's node; the **managed** node is the one it
drives. A **client** is, as in the companion protocol, the app or
program driving the manager.

## Owners

A node holds a list of at most `OWNERS` **owners**: addresses that may
manage it. Each is a [contact](companion.md#what-the-node-holds), so a
node takes first contact from each of its owners
([Who may make first contact](companion.md#who-may-make-first-contact)),
and a relay on a mast with no client to ask need take no one else. A
node that no longer holds an address as a contact no longer holds it
as an owner.

A client makes a contact an owner, or not, with the companion request
[`OWNER`](companion.md#the-requests), over its own link or over the
mesh. A node has no owners until it is given one, and cannot be
managed until then. A node MUST keep its owners across restarts, and
a [wipe](companion.md#the-requests) forgets them with the rest.

## The frames

A request and its answer each travel as a message for the node, with
[`node`](unicast-security.md#the-frame) set, in the session between
manager and managed node. The manager sends a **request**:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x05`: a request to manage |
| 1 | `n` | `frame` | one companion request, as on a [link](companion.md#frames), at most `REQUEST_MAX` bytes |

The managed node sends an **answer**:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x06`: what managing answers |
| 1 | | `frames` | one or more companion frames, each as a `u8` length and then the frame, at most `ANSWER_MAX` bytes in all |

Each companion frame inside is read as the companion protocol reads
it, at the version the manager's client gave in its last `HELLO` over
the mesh ([below](#the-connection)). A receiver MUST ignore a request
of no `frame`, or longer than `REQUEST_MAX`, and an answer that holds
no frame, is longer than `ANSWER_MAX`, or whose last length runs past
its end.

Both are messages like any other: each takes the session's next
counter, is acknowledged, and is tried again and another way as
[Frames that follow routes](forwarding.md#messages) has it. A managed
node that sleeps has a request held by its keeper, as it has a message,
and answers when it wakes.

## The connection

A managed node keeps, for each owner, a **connection** as a node keeps
one for each client of its own ([Starting](companion.md#starting)): the
version the owner's client last gave in `HELLO`, and a count of the
news it has sent on it. It holds them only in memory; after a restart
an owner's first request but `HELLO` is answered `ERROR` 6, and its
client says `HELLO` again.

**Who is answered.** A managed node that receives a request in a
session whose other end is not one of its owners MUST do nothing with
it but **refuse** it: answer `ERROR` 15, not an owner, with the
request's `seq`, in one answer of its own. It MUST NOT refuse more than
once in any `REFUSE_GAP`, counting every sender together: a request it
may not refuse it does nothing with, and does not answer. The message is
acknowledged either way, as every message is, since the acknowledgement
says that it arrived, not what was done.

A client given `ERROR` 15 SHOULD say that the node has not made this
one an owner and that only an owner can, and MUST NOT send that request
again unasked. One given no answer in `MESH_ANSWER_WAIT` SHOULD say that
either the node is out of reach or this one is not an owner.

**What may be asked.** Over the mesh a node acts on these requests,
and MUST answer any other `ERROR` 13, not over the mesh:

| Request | Over the mesh |
|---|---|
| `HELLO`, `PING`, `SET_TIME` | as over a link |
| `SYNC` | the node's own state only, [below](#syncing) |
| `SET` | any setting but region (1) and passkey (4), on [trial](#trial) |
| `SAVE_CONTACT`, `REMOVE_CONTACT`, `END_SESSION`, `OWNER` | as over a link |
| `RESTART` | as over a link |

Region is left out because a node given a new region can no longer
hear the owner that gave it, and the passkey because it is for those
in Bluetooth's reach, who have a link of their own. `SEND`, groups,
positions, updates, `OFF` and `WIPE` are left out: managing is keeping
a node working, not using it as its own user would, and a node
turned off or wiped cannot be managed back.

**One at a time.** A client MUST NOT send a request over the mesh to
a node while one it sent that node is unanswered, as over a link
([Requests, one at a time](companion.md#requests-one-at-a-time)), but
waits `MESH_ANSWER_WAIT` after its manager says the request was
delivered, not `ANSWER_WAIT`, before giving up on it.

**Answers.** A managed node puts as many of the frames a request
prompts as fit in each answer, in the order it would send them over a
link, and starts another answer when the next does not fit. Over the
mesh it sends news only in answer to `SYNC`: none unasked.

### Syncing

A `SYNC` over the mesh asks for the node's own state, not its user's.
The node sends, whatever `after` is, one `SELF`, a `CONTACT` for every
contact, a `NEIGHBOUR` for every neighbour, one `AIRTIME`, one `POWER`,
one `FIX` and one `SLEEP`, then answers `SYNCED`. It sends no message,
group, position, sharing, card or `FORGOTTEN`: those are its user's, and
managing it gives none of them away. A client keeps what such a sync
sent for that node apart from what its own node's syncs send, and
forgets contacts and neighbours of that node that it did not send, as
[Syncing](companion.md#syncing) says.

### Trial

A `SET` over the mesh is on **trial**. The node acts on it and answers
`OK` as over a link, and keeps the value it replaced. If no request
over the mesh from any of its owners arrives in the `TRIAL` seconds
after the answer, the node MUST take back the value it replaced, as if
given it by `SET`. A node keeps a trial, with the value it would take
back, across a restart, as one that applies a setting may need: it
starts the trial's `TRIAL` again from when it starts, since it may not
know how long it was off. Any request from an owner over the mesh ends
the trial, and the setting stays.

So a client SHOULD send a `PING` over the mesh once it has the answer
to a `SET`. If the setting has left the node out of reach, by a power
too low or a wake too long for the owner's patience, the `PING` does
not arrive, and within `TRIAL` the node is as it was. A second `SET`
while one is on trial ends the first trial, and starts its own.

`SET` over a link is never on trial: a client with a link is beside the
node.

## Telling the owners

A node's owners can change who its owners are: so can anyone at the node
with a link to it, over USB or over Bluetooth in its
[pairing window](companion.md#bluetooth-le). So that someone at a relay
cannot make themselves an owner unseen, a node whose owners change
tells them. When an address becomes an owner or stops being one, the
node MUST send a **notice**, a message for the node, to each address
that was an owner before the change or is one after it, but the owner
whose request over the mesh made the change, who knows:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x07`: the owners changed |
| 1 | 32 | `contact` | the address that became an owner or stopped being one |
| 33 | 1 | `owner` | 1 if it is one now, 0 if not |
| 34 | 1 | `by` | 0 if over a link, USB or Bluetooth; 1 if by an owner over the mesh |

It is exactly 35 bytes; a receiver MUST ignore one of any other length,
or with `owner` or `by` other than 0 or 1. A node that receives one
from an address in a session tells its clients with the companion
news [`OWNER_CHANGED`](companion.md#news), whether or not it manages
that node. A notice is the one thing a node sends its owners unasked.

A wipe forgets the owners, and sends no notice: the node's address goes
with them, and its owners find it gone, as they find any node they
cannot reach.

## Locking Bluetooth

An owner who will not be at a node can **lock** its Bluetooth with
companion `SET` 10. While a node is locked, it acts on no request a
client sends over Bluetooth but `HELLO` and `PING`, and answers every
other `ERROR` 14, locked. Over USB and over the mesh it is as before.
So someone who pairs with a relay in its pairing window, as anyone who
can press its button can, cannot change it; and to unlock it they must
open it to reach its USB, or be one of its owners.

A node keeps the lock across restarts, and a wipe clears it. `SELF`
says whether the node is locked. A client SHOULD say, before it locks a
node, that only USB and the node's owners can unlock it.

## Paid for

An answer is a frame of the managed node's own, and is paid for from
the own part of its [airtime budget](airtime.md#the-parts); a request
is paid for from the manager's. A sync of a relay with one contact and
three neighbours takes two answers, and with twenty neighbours four;
every other request takes one.

## Parameters

| Name | Value | |
|---|---|---|
| `OWNERS` | 4 | owners a node holds, at most |
| `REQUEST_MAX` | 128 bytes | a request's `frame`, at most: as long as a message's text |
| `ANSWER_MAX` | 128 bytes | an answer's `frames`, at most: as long as a message's text |
| `MESH_ANSWER_WAIT` | 120 s | after delivery, before a client gives a request up |
| `TRIAL` | 900 s | after a `SET` over the mesh is answered, before it is taken back |
| `REFUSE_GAP` | 60 s | after a node refuses a request, before it refuses another |

## Conformance

An implementation conforms to this section if, for
[`vectors/managing.json`](../vectors/managing.json):

* **requests** and **answers:** given the companion frames, it
  produces exactly `content`; and it reads them back from it;
* **rejected:** it ignores each `content`;
* **allowed:** over the mesh, as a managed node, it acts on the request
  of each `type` and `setting`, or answers `ERROR` 13, as `allowed`
  says;
* **owners:** as a managed node holding the owners `owners`, that last
  refused a request `refused_s` seconds before (`null`: never), it acts
  on a request in a session with `from`, refuses it with exactly
  `refusal`, or does nothing with it, as `answer` says;
* **notices:** given `contact`, `owner` and `by`, it produces exactly
  `content`; and it reads them back from it; and it ignores each notice
  among `rejected`;
* **locked:** while locked, it acts on each request over Bluetooth, or
  answers `ERROR` 14, as `allowed` says;
* **trials:** as a managed node that answered a `SET` over the mesh
  `answered_s` seconds ago and has since had a request over the mesh
  from an owner, or not, as `confirmed` says, it holds the new value,
  or the old, as `holds` says;
* **syncs:** given the state of a node, it sends exactly `answers` in
  answer to a `SYNC` over the mesh.

## What an observer learns

Nothing it does not learn of any message: requests and answers are
messages for the node, sealed in their session. An observer who can
tell a message for the node from one of words, by the
[`node` flag](unicast-security.md#not-yet-specified), may guess from
their lengths and timing that a node is being managed. The managed
node's keeper, if it sleeps, learns only that frames are held for it.

## Rationale

**Why 128 bytes.** A request and an answer are each held by the node
that sends them until they are acknowledged, as a message is, and a
message's text is at most 128 bytes ([Companion](companion.md#the-requests)).
At the same length a node holds them in the room it holds messages in,
which on the smallest boards is all the room there is. No request a
node acts on over the mesh is longer than 66 bytes.

**Why the companion protocol, inside messages.** MeshCore manages a
repeater with its own set of commands behind a password; Meshtastic
with its own admin messages. Both are a second protocol for settings
that a client already changes over its link. Carrying the companion
protocol's own frames means one encoder, one set of settings and one
list of errors for both, and an app that shows a node's state shows a
remote one's with the same code. It costs the length bytes, and the
`ERROR` 13 for what is left out.

**Why owners, not a password.** A password is sent to be checked, so
it crosses the air, even if sealed, to every node that asks for it;
anyone who learns it from a forum post or a neighbour manages the
node, and a relay cannot tell who did. An owner's address is proved by
first contact, already held by every node that sends a message, and
an owner who leaves is removed without telling a secret to the rest.
It needs a session, which costs the first contact once.

**Why the owners are contacts.** A node takes first contact from its
contacts, so an owner reaches a relay that takes no one else, and
removing the contact removes the owner: there is one list to look at,
not two.

**Why a refusal, and not silence.** A node once kept silent to anyone
but its owners, so that no one would learn which nodes can be managed.
It hid little: the acknowledgement already says the node is there and
took the request, and every node running this protocol can be managed
by someone. What silence cost was its users' time. Someone who tapped
the wrong node, or one that had not made them an owner yet, waited
`MESH_ANSWER_WAIT` for nothing, and could not tell a node that refused
them from one out of reach. A refusal is one answer of four bytes, and
says no more than that this one is not an owner: nothing of who is.

**Why one refusal a minute.** A refusal is a frame the node pays for,
asked for by anyone with a session. Counting senders together needs no
table of them, and bounds what refusals can cost at one short answer a
minute, whoever asks; an owner, who is never refused, is not slowed.
Someone whose refusal was spent on another waits, as they did when there
were none.

**Why a trial, and not a confirmation step.** A router's "commit
confirmed" asks the operator to confirm a change or have it undone. Here
any request confirms, so a client that pings after a `SET`, as it
already pings to see a node is there, confirms by reaching it; and a
change that cuts the node off cannot be confirmed by anyone. A whole
`TRIAL` is long, but a node out of reach for fifteen minutes is better
than one out of reach until someone climbs the mast.

**Why no region.** A node and its owner must share a region's settings
to hear each other at all, so a new region over the mesh is a node
lost until its trial ends, at best. Moving a mesh to new settings is
something every node does together, and is
[not yet specified](#not-yet-specified).

**Why owners are told.** Anyone who can press a relay's button can pair
with it, and anyone who can open it can plug in, and either could add
themselves as an owner and come back over the mesh whenever they liked.
No rule at the node can stop someone holding it, but a notice means the
owners know, and can remove them and lock the node. It is one message
to each owner, and only when the owners change.

**Why no news unasked.** A relay's battery running low, or a neighbour
lost, would be worth telling its owner. Each would be a message, paid
for in airtime, to an owner who may not be listening; asking costs only
when someone wants to know.

## Not yet specified

* **Firmware over the mesh.** An image of hundreds of kilobytes is
  thousands of frames, more than a profile's limit on transmitting
  gives in a day. A patch against the image a node runs, or an image
  passed from neighbour to neighbour, might fit.
* **News unasked**, beyond a notice: a node that tells its owners when
  its battery is low, or it has restarted, within an allowance of its
  own.
* **Locking USB.** Anyone with the node in their hands can wipe it or
  load other firmware, and a lock on USB would stop its owner too.
* **Moving a mesh's nodes together** to new radio settings.
* **Owners with less**: one who may see a node's state but not change
  it.
* **A node with no owner** that takes the first who asks, for a
  relay set up without a client. It would be anyone's who got there
  first.
