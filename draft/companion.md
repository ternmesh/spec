# The companion protocol

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Its numbers are
**provisional**, and its frames carry what the drafts so far let a
node know: nothing here is measured.

Everything else in this specification goes over LoRa. This section does
not. It defines the link between a node and the **client** driving it:
a phone app, a desktop client, a script. That link is in the
specification because anyone writing their own client needs a written,
stable contract to write it against, and the same test vectors as
the radio protocol has.

It defines the frames a client and a node exchange, how they are
carried on a byte stream (USB serial, TCP) and over Bluetooth LE, how a
connection starts and how either end finds the other has gone, and how
a client and a node of different ages tell what the other speaks.

Test vectors: [`vectors/companion.json`](../vectors/companion.json),
produced by
[`vectors/tools/companion.py`](../vectors/tools/companion.py).

## Goals

1. **The user's words, not the protocol's.** A client sees contacts,
   messages and what became of them, neighbours and a share of the air.
   It never handles a session, a key or a counter, and cannot ask a
   node to put anything on the air that the radio protocol keeps off
   it.
2. **One protocol on every link.** The same frames over USB, TCP and
   Bluetooth. Only how a frame is delimited differs.
3. **Small enough for the smallest node.** Fixed fields in a fixed
   order, no schema compiler and nothing to allocate. The longest
   frame is 180 bytes, so a node needs one buffer of that size each
   way.
4. **A client that was away catches up.** A node says what it holds
   when asked, and what changes as it changes. A client that missed
   something can tell, and asks again.
5. **Beside the console, not instead of it.** A node's serial port
   also carries its text console. The protocol's frames can be told
   apart from text, and text from frames, byte by byte.

## Notation

Fields are big-endian. Kinds:

| Kind | Bytes | |
|---|---|---|
| `u8`, `u16`, `u32` | 1, 2, 4 | unsigned |
| `i8`, `i16`, `i32` | 1, 2, 4 | two's complement |
| `addr` | 32 | an [address](first-contact.md#addresses) |
| `gid` | 8 | a [group's id](#groups) |
| `digest` | 32 | a SHA-256 digest ([FIPS 180-4](https://doi.org/10.6028/NIST.FIPS.180-4)) |
| `str` | 1 + `n` | a `u8` length `n`, then `n` bytes of UTF-8; each field gives its longest `n` |
| `bytes` | 1 + `n` | a `u8` length `n`, then `n` bytes of anything; each field gives its longest `n` |

A **routing id** is a `u32`, as in [Routes](routing.md#routing-ids).
**Time** is a `u32` of seconds since 1970-01-01 00:00 UTC, ignoring
leap seconds; 0 means the node does not know it.

## Frames

Every frame starts with two bytes:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `type` | what the frame is |
| 1 | 1 | `seq` | below |
| 2 | | fields | as the type gives, in order |

A frame is at most `MAX_FRAME` bytes, 180.

Types fall in three ranges:

| `type` | Kind | Sent by | `seq` is |
|---|---|---|---|
| `0x01`–`0x3F` | **request** | the client | chosen by the client |
| `0x40`–`0x7F` | **answer** | the node | the `seq` of the request it answers |
| `0x80`–`0xBF` | **news** | the node | the node's news count, [below](#news) |

`0x00` and `0xC0`–`0xFF` are reserved.

**Reading a frame.** A receiver reads the fields its version defines
for the type, and MUST ignore any bytes after them: that is how a later
version adds a field to a frame. A frame is **malformed** if it is
shorter than two bytes or than its fields, if a `str` is longer than
its field allows, or if a `str` is not valid UTF-8.

* A node that receives a request it cannot read MUST answer `ERROR`
  with code 1 if its type, or the setting it names, is one its version
  does not define, and code 2 if it is malformed. A frame shorter than
  two bytes is not answered.
* A client MUST ignore news of a type it does not know. That is how a
  later version adds news. It MUST discard any other frame it cannot
  read.

### Requests

| `type` | Request | Fields | Answered by |
|---|---|---|---|
| `0x01` | `HELLO` | `version` `u8` | `INFO` |
| `0x02` | `SYNC` | `after` `u32` | news, then `SYNCED` |
| `0x03` | `PING` | | `OK` |
| `0x04` | `SET_TIME` | `time` `u32` | `OK` |
| `0x05` | `SET` | `setting` `u8`, then its value | `OK` |
| `0x10` | `SEND` | `ref` `u32`, `to` `addr`, `text` `str` up to 128 | `QUEUED` |
| `0x11` | `READ` | `through` `u32` | `OK` |
| `0x18` | `SAVE_CONTACT` | `address` `addr`, `name` `str` up to 31 | `OK` |
| `0x19` | `REMOVE_CONTACT` | `address` `addr` | `OK` |
| `0x1A` | `END_SESSION` | `address` `addr` | `OK` |
| `0x20` | `MAKE_GROUP` | `name` `str` up to 31 | `MADE` |
| `0x21` | `LEAVE_GROUP` | `group` `gid` | `OK` |
| `0x22` | `NAME_GROUP` | `group` `gid`, `name` `str` up to 31 | `OK` |
| `0x23` | `SEND_GROUP` | `ref` `u32`, `group` `gid`, `text` `str` up to 128 | `QUEUED` |
| `0x24` | `SEND_INVITE` | `group` `gid`, `to` `addr` | `QUEUED` |
| `0x25` | `JOIN` | `id` `u32` | `OK` |
| `0x26` | `GROUP_LINK` | `group` `gid` | `LINK` |
| `0x27` | `JOIN_LINK` | `link` `str` up to 102 | `MADE` |
| `0x30` | `UPDATE_BEGIN` | `size` `u32`, `digest` `digest` | `UPDATING` |
| `0x31` | `UPDATE_DATA` | `offset` `u32`, `data` `bytes` up to 172 | `OK` |
| `0x32` | `UPDATE_END` | | `OK` |
| `0x33` | `SET_POSITION` | `lat` `i32`, `lon` `i32`, `altitude` `i16`, `accuracy` `u16`, `age` `u16` | `OK` |
| `0x34` | `SHARE` | `contact` `addr`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` | `OK` |
| `0x35` | `SHARE_GROUP` | `group` `gid`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` | `OK` |

Any request may instead be answered by `ERROR`.

### Answers

| `type` | Answer | Fields |
|---|---|---|
| `0x40` | `OK` | |
| `0x41` | `ERROR` | `code` `u8` |
| `0x42` | `INFO` | `version` `u8`, `firmware` `str` up to 31, `board` `str` up to 31, `release` `str` up to 31 |
| `0x43` | `SYNCED` | `news` `u8` |
| `0x44` | `QUEUED` | `id` `u32` |
| `0x45` | `MADE` | `group` `gid` |
| `0x46` | `UPDATING` | `offset` `u32` |
| `0x47` | `LINK` | `link` `str` up to 102 |

`firmware` names the node's software, for a person to read. A client
MUST NOT decide what the node supports from it: that is what `version`
is for. `board` and `release` are for a client to read, and are how it
finds firmware for the node ([Updating the firmware](#updating-the-firmware)):
`board` names the hardware the node's firmware is built for, such as
`heltec-v3`, in lowercase letters, digits and hyphens, and is empty if
the node cannot be updated over this protocol; `release` is the version
of that firmware, as [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
writes one, without a leading `v`, and is empty if it has none, as a
build made by hand may not.

`news` in `SYNCED` is the node's [count](#news) as it answers: the
`seq` its next news frame will carry. It is how a client knows it
received all of a [sync](#syncing).

Error codes:

| `code` | |
|---|---|
| 1 | a request, or a setting, this node's version does not define |
| 2 | malformed |
| 3 | a value the node refuses: a region it does not have, a power it cannot send at, empty text |
| 4 | not a [valid](first-contact.md#addresses) address, or the node's own |
| 5 | no room: the node cannot hold another contact, message or group, or the image an [update](#updating-the-firmware) offers |
| 6 | `HELLO` first |
| 7 | the Bluetooth link's MTU is too small ([below](#bluetooth-le)) |
| 8 | not now: the node cannot act on this request until it has finished something else |
| 9 | not held: a group the node is not in, or an invite it does not hold |
| 10 | not where the update is: no [update](#updating-the-firmware) is under way, or not at that offset |
| 11 | not an image this node runs: the update is discarded |
| 12 | not a contact: an address the node does not hold as one |

Other codes are reserved. A client MUST treat one it does not know as
a refusal.

### News

| `type` | News | Fields |
|---|---|---|
| `0x80` | `SELF` | `address` `addr`, `role` `u8`, `region` `str` up to 15, `power` `i8`, `time` `u32`, `cards` `u8`, `card_name` `str` up to 31 |
| `0x81` | `CONTACT` | `address` `addr`, `session` `u8`, `name` `str` up to 31 |
| `0x82` | `CONTACT_GONE` | `address` `addr` |
| `0x83` | `MESSAGE` | `id` `u32`, `contact` `addr`, `time` `u32`, `flags` `u8`, `state` `u8`, `reason` `u8`, `wait` `u16`, `text` `str` up to 128 |
| `0x84` | `STATE` | `id` `u32`, `state` `u8`, `reason` `u8`, `wait` `u16` |
| `0x85` | `NEIGHBOUR` | `routing_id` `u32`, `role` `u8`, `snr` `i8`, `heard` `u16` |
| `0x86` | `NEIGHBOUR_GONE` | `routing_id` `u32` |
| `0x87` | `AIRTIME` | `period` `u32`, `allowed` `u32`, `used` `u32`, `wait` `u32` |
| `0x88` | `POWER` | `millivolts` `u16`, `percent` `u8`, `flags` `u8` |
| `0x89` | `ASKED` | `address` `addr`, `why` `u8` |
| `0x8A` | `GROUP` | `group` `gid`, `name` `str` up to 31 |
| `0x8B` | `GROUP_GONE` | `group` `gid` |
| `0x8C` | `GROUP_MESSAGE` | `id` `u32`, `group` `gid`, `from` `u32`, `time` `u32`, `flags` `u8`, `state` `u8`, `reason` `u8`, `wait` `u16`, `text` `str` up to 128 |
| `0x8D` | `INVITE` | `id` `u32`, `contact` `addr`, `group` `gid`, `time` `u32`, `flags` `u8`, `state` `u8`, `reason` `u8`, `wait` `u16`, `name` `str` up to 31 |
| `0x8E` | `POSITION` | `contact` `addr`, `precision` `u8`, `lat` `i32`, `lon` `i32`, `altitude` `i16`, `accuracy` `u8`, `age` `u32` |
| `0x8F` | `GROUP_POSITION` | `group` `gid`, `from` `u32`, `precision` `u8`, `lat` `i32`, `lon` `i32`, `altitude` `i16`, `accuracy` `u8`, `age` `u32` |
| `0x90` | `SHARING` | `contact` `addr`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` |
| `0x91` | `GROUP_SHARING` | `group` `gid`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` |
| `0x92` | `CARD` | `address` `addr`, `heard` `u32`, `name` `str` up to 31 |
| `0x93` | `CARD_GONE` | `address` `addr` |

Each news frame but `STATE`, the four `_GONE`s and `ASKED` is a
**record**: the whole of one thing as the node holds it now. A record
replaces any the client holds for the same thing. `STATE` replaces
those fields of the `MESSAGE`, `GROUP_MESSAGE` or `INVITE` with its
`id`. `ASKED` is something that
happened, and the node does not hold it: a [sync](#syncing) does not
send it again.

**The node's count.** A node keeps a count of the news it has sent on
each connection. It sets it to 0 when it answers a `HELLO`. Each news
frame carries the count in `seq`, and the count then goes up by one,
from 255 to 0. A client that receives news whose `seq` is not the one
it expects has missed some, and SHOULD [sync](#syncing) again.

## What the node holds

**Itself** (`SELF`). `role` is 0 for a leaf and 1 for a relay
([Roles](routing.md#roles)). `region` is the name of the
[profile](phy.md#profiles) the node is set to, such as `EU868`, or
empty if none is. `power` is what it transmits at most, in dBm. `time`
is its clock. `cards` is 1 if the node sends [cards](#cards), 0 if
not, and `card_name` is the name its cards carry, as `SET` 5 and 6 set
them.

**Contacts** (`CONTACT`). A contact is an address the user has
saved, with a name. `session` is 1 if the node shares a session with
it ([First contact](first-contact.md)), 0 if not. The name is the
user's, for the user: it is kept on the node and given to clients, and
a node MUST NOT send it on the air.

**Messages** (`MESSAGE`). Each has an `id`, given by the node: it is
at least 1, unique on the node and greater than every `id` before it,
so a client can ask for those after one it holds. `contact` is the address the
message went to or came from, whether or not it is a saved contact.
`time` is when it was written or received, by the node's clock. `flags`
bit 0 is set once a received message has been [read](#reading); the
other bits are 0. `text` is what the user wrote, at least one byte.

A message's `state` is where it is:

| `state` | | For |
|---|---|---|
| 0 | **waiting**: not yet on the air | sent |
| 1 | **sent**: the first neighbour has been heard passing it on ([Hops](forwarding.md#hops)) | sent |
| 2 | **delivered**: its destination's acknowledgement came back ([Messages](forwarding.md#messages)) | sent |
| 3 | **not delivered**: its source gave it up | sent |
| 4 | **received** | received |

A sent message's state only goes forward through this table, except
that one being tried again goes from sent back to waiting. A node MUST
NOT give a message a state more certain than it knows: in particular, a
message is not sent until a neighbour has been heard passing it on.

`reason` says why a waiting message waits, and is 0 in every other
state:

| `reason` | Waiting for |
|---|---|
| 0 | nothing the node can name |
| 1 | a route to its destination |
| 2 | a session: [first contact](first-contact.md) is under way |
| 3 | the region's limit on transmitting ([Profiles](phy.md#profiles)) |
| 4 | the node's airtime budget |
| 5 | the radio: other frames go first |

`wait` is the node's estimate, in seconds, of how long until it goes,
0 if it has none, and at most `0xFFFF`.

**Neighbours** (`NEIGHBOUR`). The nodes whose announces the node hears,
by routing id. `role` is as in `SELF`. `snr` is the signal-to-noise
ratio of the last frame heard from it, in quarters of a dB. `heard` is
how many seconds ago that was, up to `0xFFFF`, as of when the record
was sent. A client knows a neighbour's address only if it can match the
routing id to one, by working out the [routing id](routing.md#routing-ids)
of each address it knows.

**The air** (`AIRTIME`). The region's limit on transmitting, as the
node is spending it. `period` is the length of the period the profile
limits, in seconds, 0 for a profile with no limit. `allowed` is the
time on air the profile allows in a period, and `used` how much of it
the node has used in the period ending now, both in milliseconds.
`wait` is how many milliseconds until the node could send its longest
frame, 0 if it could now. A profile with no limit gives `allowed` and
`wait` as 0.

**Power** (`POWER`). `millivolts` is the battery's voltage, 0 if the
node cannot measure it. `percent` is the node's estimate of the charge
left, 255 if it has none. `flags` bit 0: the battery is charging. Bit
1: the node is running from external power. The other bits are 0.

### Groups

**Groups** (`GROUP`). A [group](groups.md) the node holds, with the
user's name for it. A client knows a group by its **id**, which the
node works out from the group's secret `G`:

```
gid = Expand(G, "tern v0 group id", 8)
```

with `Expand` as in [Secured unicast frames](unicast-security.md#notation).
The id is the same on every node that holds the group, and gives
nothing of the secret away. Like the name, it is for the node and its
clients: a node MUST NOT send either on the air, but for the name in an
[invite](groups.md#invites). No frame of this protocol carries a
group's secret, but for a [join code](groups.md#join-codes), which
carries it on purpose, and only when the user asks: in `LINK`, when
the user asks to show one, and in `JOIN_LINK`, when they join from one.

**Group messages** (`GROUP_MESSAGE`). A message written to a group, or
received from one. Its `id` is from the same count as a `MESSAGE`'s,
so `READ`, `STATE` and a sync's `after` mean for it what they mean for
a `MESSAGE`. `from` is the routing id the frame gave for its writer,
and 0 for a message this node wrote. It is
[what a member claimed](groups.md#receiving), and a client that shows
it as a name it knows by that [routing id](routing.md#routing-ids)
SHOULD NOT show it as proved. `time`, `flags` and `text` are as for a
`MESSAGE`.

A group message this node wrote is **waiting** until it has gone on the
air, with `reason` 4 while it waits for
[the node's allowance](flooding.md#the-allowance), and **sent** from
then on. It is never delivered: nothing answers a flood, and a writer
does not learn who received it. It is **not delivered** only if its
group is [left](#the-requests) while it still waits. One received is
**received**.

**Invites** (`INVITE`). An [invite](groups.md#invites) to a group, sent
to `contact` or received from it. Its `id` is from the same count
again. `group` is the id of the group it is to, and `name` what the
inviter calls it. `state`, `reason` and `wait` are a `MESSAGE`'s: an
invite is a unicast message, and is waiting, sent, delivered or not
delivered as one is, or received. `flags` bit 0 is set once a received
invite has been [read](#reading).

A node holds the secret a received invite carried for as long as it
holds the invite, so that the user can [`JOIN`](#the-requests) later.
It MUST NOT hold the group itself until then.

**Join codes.** A client shows a group's [join
code](groups.md#join-codes) by asking the node for it with
`GROUP_LINK`, and joins a group from one by handing the node the code
with `JOIN_LINK`. Either way the code passes through the client as the
link, text the client shows or was given, and the client need not read
the secret out of it. A client MUST NOT send `GROUP_LINK` unless its
user asked to see or share that group's code, and MUST NOT send
`JOIN_LINK` unless its user asked to join from that code. It MUST NOT
keep a link it was given by `LINK`, nor one it sent with `JOIN_LINK`,
once it has shown or sent it: a client that does not keep the secret
has none to lose.

### Positions

[Positions](positions.md) are shared only with the contacts and groups
the user chooses, at the precision the user chooses. A client gives
the node its own position, and turns sharing on and off; the node
works out the cells, decides when each goes on the air, and tells
clients what it receives.

**Positions received** (`POSITION`, `GROUP_POSITION`). The position the
node [holds](positions.md#reading-a-position) from a contact, or from
a routing id in a group. A node holds none from an address that is not
a contact. `from` is as for a `GROUP_MESSAGE`: what a
member claimed. `precision` is the position's, and `lat` and `lon` are
the centre of its cell, in 10⁻⁷ degree, north and east positive; the
cell is `360 / 2^precision` degrees each way. `altitude` is in metres,
`-32768` if the position gave none, and `accuracy` in metres, 0 if it
gave none. `age` is how many seconds old the fix was as of when the
record was sent, from the position's own `age` and the time since the
node received it. A record whose `precision` is 0 says the node holds
no position from that sender, and its other fields are 0.

**Sharing** (`SHARING`, `GROUP_SHARING`). How the node shares its
position with a contact or a group, as [`SHARE`](#the-requests) set it.
`precision` is 1 to 24, or 0 when sharing is off, and then the other
fields are 0. `fields` bit 0: altitude goes with each position. Bit 1:
accuracy does. The other bits are 0. `interval` is in seconds.
`minutes` is how many minutes are left until the node turns sharing
off, rounded up, as of when the record was sent, and 0 if it is on
until it is turned off.

### Cards

A [card](cards.md) is how a node whose user chooses says, to the nodes
near it, who it is: its address and a name. A client turns the node's
cards on and off and sets the name they carry, with
[`SET`](#the-requests) 5 and 6; the node signs and sends them, and
tells clients of the cards it holds from others, as **who is about**.

**Cards held** (`CARD`). A card the node
[holds](cards.md#receiving), one for each address. `name` is the name
that card carried, which its sender chose, and may be empty. `heard` is
how many seconds ago the node accepted that card, as of when the record
was sent. A card's `number` stays on the node: a client has no use for
it.

A card's name is a claim its sender made, not a name the user gave, and
a client SHOULD show it as such, beside the address's
[short code](sharing.md#the-short-code), and never in the place of a
contact's name. A node holds cards whether or not it sends its own:
receiving them puts nothing on the air.

**Meeting someone from a card.** A client makes a card's sender a
contact with `SAVE_CONTACT`, giving the card's `address` and whatever
name the user chooses, which it MAY offer the card's `name` for. That
lets the sender in when it makes [first
contact](#who-may-make-first-contact), and a `SEND` to the address
makes first contact from this end. A client MUST NOT send either for a
card's address unless its user asked it to, as
[Presence cards](cards.md#receiving) requires of the node. Saving a
contact changes nothing about the card, which the node keeps as long as
it would have.

A client that receives `ASKED` for an address it holds a card from
MAY show the card's name with it, as its sender's claim: the address in
an `ASKED` is proved, and the card is signed by it.

### Who may make first contact

A session starts with [first contact](first-contact.md), which either
end may begin. A node begins it when it has a message for an address it
shares no session with. When another node begins it, this node learns
which address is asking only from the handshake's third message, which
proves it, and decides then.

A node MUST take first contact from an address that is a contact, if
it has room for another session or shares one with that address
already. A node holds at most one session with an address: first
contact with an address it shares a session with puts the new session
in the old one's place, once the handshake is complete, and needs no
more room. That is how two nodes recover when only one of them still
holds their session. Whether it takes first contact from any other address is its
own choice: a node with no client to ask, such as a relay on a mast,
may have to take anyone.

A node that refuses first contact from an address that has proved
itself MUST send `ASKED` with that address, unless it has sent one for
that address in the last `QUIET` seconds, when it MAY leave it out: a
node that is refused asks again within seconds. `why` is:

| `why` | The node refused because |
|---|---|
| 1 | the address is not a contact |
| 2 | it has no room for another session |

Other values are reserved, and a client treats one it does not know as
a refusal it cannot name.

So a client lets a node in by saving it as a contact, and makes room
by [ending a session](#the-requests). Neither tells the node that
asked: it is taken the next time it makes first contact.

### When news is sent

A node with a client that has said `HELLO` MUST send that client:

* `MESSAGE` when a message is sent or received, and when a received
  message is marked read; `GROUP_MESSAGE` and `INVITE` likewise;
* `STATE` when the `state` or `reason` of any of the three changes;
* `GROUP` and `GROUP_GONE` when a group is made, joined, renamed or
  left;
* `CONTACT` and `CONTACT_GONE` when a contact is saved, renamed,
  removed, or gains or loses a session;
* `SELF` when anything in it but `time` changes;
* `POSITION` and `GROUP_POSITION` when a position is received, and
  when one is forgotten, with `precision` 0;
* `SHARING` and `GROUP_SHARING` when sharing is turned on, changed,
  turned off or runs out, and, with `precision` 0, when it ends because
  the contact is removed or the group left;
* `NEIGHBOUR_GONE` when the node forgets a neighbour;
* `CARD` when the node accepts a card, and `CARD_GONE` when it forgets
  one;
* `ASKED` when it refuses [first contact](#who-may-make-first-contact),
  as that section says.

A `minutes`, an `age` or a `heard` that only counts on is not a change.

It SHOULD send `NEIGHBOUR`, `AIRTIME` and `POWER` when they change,
and MAY send each no more often than once every `QUIET` seconds, so
that a neighbour heard every second does not fill the link.

What changes because of a request from one client is sent as news to
every client, the one that asked included: a client sees its own
`SEND` arrive as a `MESSAGE`.

## Starting

A connection starts with `HELLO`. Until a node has answered a `HELLO`
on a connection, it MUST answer every other request on it with
`ERROR` 6, and MUST NOT send news on it.

`HELLO` carries the client's version and `INFO` the node's. Each end
then uses only what both versions define: a client MUST NOT send a
request that the node's version does not define, and a node MUST NOT
send a frame that the client's version does not define, nor a field of
a frame that the client's version does not define. This section is
version 7. Version 6 is the same without
[join codes](groups.md#join-codes): the requests `0x26` and `0x27`,
and `LINK`. Version 5 is version 6 without [cards](#cards): the settings
5 and 6, `SELF`'s `cards` and `card_name`, and the news `CARD` and
`CARD_GONE`. Version 4 is version 5 without [positions](#positions):
the requests `0x33` to `0x35`, error 12, and the news `POSITION`,
`GROUP_POSITION`, `SHARING` and `GROUP_SHARING`. Version 3 is version 4
without [updates](#updating-the-firmware):
the requests `0x30` to `0x32`, `UPDATING`, errors 10 and 11, and
`INFO`'s `board` and `release`. Version 2 is version 3 without
`SYNCED`'s `news`. Version 1
is version 2 without [groups](#groups): the
requests `0x20` to `0x25`, `MADE`, error 9, and the news `GROUP`,
`GROUP_GONE`, `GROUP_MESSAGE` and `INVITE`. Version 0 is version 1
without `END_SESSION` and `ASKED`. A receiver reads a frame by the
version both ends speak: a client of version 3 reads a `SYNCED` from a
node of version 2 as the two bytes it is. A client learns that version
from `INFO` itself, so it reads an `INFO` by the lesser of its own
version and the `version` the `INFO` carries. A client of an earlier version is
not told of group messages or invites at all: their `id`s are ones it
never sees. One of version 4 or earlier is told of no positions, and
of no sharing. One of version 5 or earlier is told of no cards, and
is sent a `SELF` without `cards` and `card_name`. A node MUST answer a
request, or a setting, that the client's version does not define with
`ERROR` 1, as it does one its own version does not: it could not tell
that client what the request changed. A
receiver reads a frame of a type that only a later version defines as
one of a type it does not know, whatever its own version: a node of
version 5 answers a `SHARE` from a client of version 4 with `ERROR` 1,
and a client of version 4 ignores a `POSITION`. Likewise, a node of
version 6 answers a `SET` of setting 5 from a client of version 5 with
`ERROR` 1, and a client of version 5 ignores a `CARD`.
Later versions only add types, settings, error codes and
fields at the end of a frame, so any two versions can talk. A change
that cannot be made that way is a new protocol, with its own magic and
its own Bluetooth service.

A client then, typically, sets the node's clock and syncs:

```
client                         node
HELLO       seq 1, version 7  ─▶
                              ◀─  INFO        seq 1, version 7
SET_TIME    seq 2             ─▶
                              ◀─  OK          seq 2
SYNC        seq 3, after 0    ─▶
                              ◀─  SELF        seq 0   ─┐
                              ◀─  CONTACT     seq 1    │ news, counted
                              ◀─  MESSAGE ... seq 2    │ from 0 since
                              ◀─  ...                  │ the HELLO
                              ◀─  SYNCED      seq 3   ─┘ answers the SYNC
```

A `HELLO` on a connection that has had one starts it again: the count
goes back to 0.

### Syncing

`SYNC` asks for everything. The node sends news: one `SELF`, then a
`CONTACT` for every contact, a `GROUP` for every group, a `MESSAGE`,
`GROUP_MESSAGE` or `INVITE` for every one it holds whose `id` is
greater than `after`, in order of `id`, a `NEIGHBOUR` for every
neighbour, a `POSITION` or `GROUP_POSITION` for every position it
holds, a `SHARING` or `GROUP_SHARING` for every contact or group it
shares its position with, a `CARD` for every card it holds, one
`AIRTIME` and one `POWER`. Then it answers `SYNCED`. News that a change
prompts while it syncs is sent as at any other time, among the rest.

For contacts, groups, neighbours, positions, sharing and cards, a sync
is the whole list: a client that receives `SYNCED` MUST forget every
contact, group, neighbour, position and card it holds that the sync
did not send, as if it had received its `_GONE` or a position's record with `precision`
0, and take sharing to be off with every contact and group the sync
sent no `SHARING` or `GROUP_SHARING` for. Messages are not: a sync
sends only those after `after`, and a client keeps the rest.

A client that has missed news since it sent the `SYNC`, either by a
gap in the count or because the count it expects next is not the
`SYNCED`'s `news`, cannot tell what the sync did not send from what
it lost. It MUST NOT forget anything on that sync's account, and
SHOULD sync again.

A client that holds messages already gives the greatest `id` it holds
as `after`. One that has [missed news](#news) gives one less than the
least `id` of any message it holds that is still waiting or sent,
since those are the ones whose state may have changed unseen. A group
message that is sent is not one of them: it stays sent. `after`
of 0 asks for every message.

A client that speaks a later version to a node than it did when it
last synced with it gives `after` of 0, once. The node may hold
records of kinds the client was not sent then, with `id`s below ones
it was.

A node keeps only so many messages, and MAY forget the oldest without
news. A client that wants them keeps its own copy.

### Requests, one at a time

A client MUST NOT send a request while one it sent is unanswered: a
node needs room for only one. A client that has had no answer within
`ANSWER_WAIT` gives up on it; for `SYNC`, the wait starts again with
each news frame. An answer whose `seq` is not that of the request the
client is waiting on is one it gave up on, and the client MUST ignore
it.

A request given up on may have been acted on. Every request but
`SEND`, `SEND_GROUP`, `SEND_INVITE`, `MAKE_GROUP` and `UPDATE_END` can
be sent again without harm: a `JOIN_LINK` sent twice joins one group,
since the second finds it held. `SEND_GROUP` carries a `ref` as `SEND` does, under the
same rule, with `group` in the place of `to`. An invite sent twice is
two invites to one group, and a group made twice is two groups, one of
which the user leaves: neither is worth a number to prevent. `SEND` carries `ref`, the client's own
number for the message, which it SHOULD choose at random for each new
message: several clients may drive one node, and a client may restart,
so a counter would repeat another's. A node that receives a `SEND`
whose `ref`, `to` and `text` are all those of one of the last `REFS`
messages it accepted MUST NOT send another message, and answers
`QUEUED` with the `id` it gave the first. So a client that sends again
with the same `ref` sends one message, whatever became of the first
try, and two different messages are never taken for one.

### Going quiet

A client sends a request no later than `IDLE` seconds after the answer
to its last, `PING` if it has nothing else to ask, whether or not news
is arriving. If one is
unanswered after `ANSWER_WAIT`, the node has gone, and the client
SHOULD close the connection and open it again.

A node learns that a Bluetooth or TCP client has gone when the
connection closes. Over USB serial it cannot: the port stays open on
the node's side whatever the computer does, and the next program to
open it may be a terminal. So a node on a serial port that has
received no request for `LAPSE` seconds since it answered the last one
MUST treat the connection as ended: it stops sending news, and answers any request but `HELLO` with
`ERROR` 6, as before the first `HELLO`. A client that receives
`ERROR` 6 after its `HELLO` was answered has been taken for gone, and
starts again with `HELLO` and a [sync](#syncing).

## The requests

**`SET_TIME`** sets the node's clock. A node SHOULD keep the time it
was given, counting on from it, until it is given another.

**`SET`** changes one setting:

| `setting` | Name | Value | |
|---|---|---|---|
| 1 | region | `str` up to 15 | a [profile](phy.md#profiles) name |
| 2 | role | `u8` | 0 leaf, 1 relay |
| 3 | power | `i8` | the most the node transmits at, in dBm |
| 4 | passkey | `u32` | the [Bluetooth](#bluetooth-le) passkey, 0 to 999999, or `0xFFFFFFFF` for a random one each time |
| 5 | cards | `u8` | 1 to send [cards](#cards), 0 to send none |
| 6 | card name | `str` up to 31 | the name the node's cards carry; empty for none |

A node MUST refuse, with `ERROR` 3, a region it does not have and a
power its radio cannot send at or that would let it radiate more than
its profile allows. A node MAY restart to apply a setting, after it
has answered: the connection then drops, and the client starts again.

A node sends no cards until it is given `SET` 5 with 1, and stops when
given it with 0; it MUST refuse any other value with `ERROR` 3. When
it sends them is [Presence cards](cards.md#sending)' rule, which
turning them off and on does not reset. Cards
are off on a node that has never been told, and its card name is
empty. The card name is the [`name`](cards.md#the-frame) in each card
the node sends from then on, and the one name a node puts on the air
in clear. A node keeps it while its cards are off. A client MUST NOT
send `SET` 5 with 1, or change the card name, unless its user asked it
to: being seen is the user's choice, as sharing a position is.

**`SEND`** sends `text` to the node at `to`, as a new message. The
answer, `QUEUED`, means the node has the message and has given it the
`id` in the answer. It says nothing about the air: that is what the
message's state is for. A node MUST refuse an invalid `to`, or its own
address, with `ERROR` 4, and empty `text` with `ERROR` 3. It sends to
an address whether or not it is a contact, making first contact if it
has no session.

**`READ`** marks as read every received message whose `id` is
`through` or less, and every received group message and invite
likewise, if the client's version defines them. A client of an earlier
version was never sent those, so its user has not seen them, and its
`READ` leaves them unread. It is how a client tells the node, and
every other client, that the user has seen them.

**`SAVE_CONTACT`** saves `address` as a contact with `name`, or
renames it if it is one already. An empty name is a name. A node MUST
refuse an invalid address, or its own, with `ERROR` 4.

**`REMOVE_CONTACT`** removes the contact. It removes the name, ends
any sharing of the node's position with the address, and forgets the
[position](positions.md#reading-a-position) held from it, and nothing
else: messages to and from the address are kept, and so is any session
with it. A node answers `OK` for an address that is not a contact.

**`END_SESSION`** ends the session the node shares with `address`: the
node forgets the session's keys, and can neither send to that address
nor read what it sends until first contact is made again. The contact,
if it is one, is kept, and so are the messages. A message to the
address that is waiting or sent becomes not delivered, whether or not
it has been on the air: the node sends no frame of it again, and an
acknowledgement that comes for it later changes nothing. A node answers
`OK` for an address it shares no session with, and `ERROR` 8 if it
cannot forget the session now.

Nothing goes on the air, so the other node is not told and keeps its
half. What it sends is not read, and is not acknowledged. The session
starts again when this node makes first contact, by a `SEND` to the
address, or when the other node does, after its own session is ended.

**`MAKE_GROUP`** makes a new [group](groups.md), with a secret the
node draws, and holds it under `name`. The answer, `MADE`, gives its
id. A node with no room for another group answers `ERROR` 5.

**`LEAVE_GROUP`** leaves the group: the node erases its secret and its
keys, and ends any sharing of its position with the group. Its
messages are kept; one still waiting to go to it, and an invite to it
still waiting, become not delivered, since neither will now be sent. Nothing goes on the air, so the other members are not
told. A node answers `OK` for a group it does not
hold.

**`NAME_GROUP`** changes the user's name for a group the node holds.
An empty name is a name. A node answers `ERROR` 9 for a group it does
not hold.

**`SEND_GROUP`** sends `text` to the group, as a new group message.
`QUEUED` means what it means for `SEND`. A node MUST refuse a group it
does not hold with `ERROR` 9, and empty `text` with `ERROR` 3.

**`SEND_INVITE`** sends the node at `to` an invite to the group, with
the name this node holds the group under. It goes as a `SEND` does,
first contact included, and `QUEUED` gives the invite's `id`. A node
MUST refuse a group it does not hold with `ERROR` 9, and an invalid
`to`, or its own address, with `ERROR` 4.

**`JOIN`** takes the group that the received invite `id` is to, under
the name the invite gave. A node MUST answer `ERROR` 9 if it holds no
such invite, or the invite is one it sent, and `ERROR` 5 if it has no
room for another group. It answers `OK` for a group it holds already,
and changes nothing.

**`GROUP_LINK`** asks for the [join code](groups.md#join-codes) of a
group the node holds, with the name the node holds it under, and
`LINK` answers it with the code's link, as that section writes it. A
node MUST refuse a group it does not hold with `ERROR` 9. Nothing goes
on the air, and nothing changes: the same group's link is the same
until it is renamed.

**`JOIN_LINK`** takes the group a join code is for, under the name the
code gives, and `MADE` answers it with the group's id. A node MUST read
`link` as [Groups](groups.md#join-codes) says a reader does, and
refuse one it reads no group from with `ERROR` 3. It answers `ERROR` 5
if it has no room for another group, and, for a group it holds
already, `MADE` with its id, changing nothing. Nothing goes on the
air: the node is a member from then on, and the others learn of it only
when it writes.

**`SET_POSITION`** gives the node the client's position: `lat` and
`lon` in 10⁻⁷ degree, WGS 84, north and east positive; `altitude` in
metres above the WGS 84 ellipsoid, or `-32768` if the client has none;
`accuracy` in metres, or 0 if it has none; and `age`, how many seconds
old the fix is. The node uses it as [Positions](positions.md#sharing)
says, and sends nothing on the air because of it unless sharing is on.
A node MUST refuse a `lat` beyond ±900000000 or a `lon` beyond
±1800000000 with `ERROR` 3. A client SHOULD give the node its position
when it moves, and SHOULD NOT give it more often than every few
seconds.

**`SHARE`** turns sharing of the node's position with `contact` on,
changes it, or, with `precision` 0, turns it off. `precision`, `fields`
and `interval` are as in `SHARING`; `minutes` is how long sharing
lasts, from now, 0 for until it is turned off. A node MUST refuse an
invalid `contact`, or its own address, with `ERROR` 4, and an address
that is not a contact with `ERROR` 12. It MUST refuse a `precision`
above 24, a bit of `fields` that is not defined, and an `interval`
below [`POSITION_MIN`](positions.md#parameters), with `ERROR` 3, unless
`precision` is 0, when it ignores the other three. Turning off sharing
that is off is `OK`, and changes nothing.

**`SHARE_GROUP`** is `SHARE` for a group the node holds, with
`POSITION_GROUP_MIN` in the place of `POSITION_MIN`. A node MUST refuse
a group it does not hold with `ERROR` 9.

A client MUST NOT send `SHARE` or `SHARE_GROUP` that the user did not
ask for: the choice to share, with whom, and how exactly, is the
user's.

## Updating the firmware

A client can give a node new firmware over this protocol: an **image**,
which is whatever the node's hardware runs, written as one file. What
an image holds, and where a client finds one, is the business of the
firmware and of whoever publishes it, not of this section: a client
finds one by the `board` and `release` in [`INFO`](#answers). A node
whose `board` is empty answers `UPDATE_BEGIN` with `ERROR` 5.

An update is three requests:

```
client                                 node
UPDATE_BEGIN  size, digest        ─▶
                                  ◀─  UPDATING  offset 0
UPDATE_DATA   offset 0, 172 bytes ─▶
                                  ◀─  OK
UPDATE_DATA   offset 172, ...     ─▶
                                  ◀─  OK
...
UPDATE_END                        ─▶
                                  ◀─  OK
                                        the node restarts, running the image
```

**`UPDATE_BEGIN`** says that an image of `size` bytes, whose SHA-256 is
`digest`, follows. A node MUST refuse a `size` of 0 with `ERROR` 3, and
one larger than it has room to hold with `ERROR` 5. It answers
`UPDATING` with the `offset` the client sends from. If an update with
the same `size` and `digest` is under way, as when a client lost its
link part of the way through, `offset` is how many bytes of it the
node holds: a node that cannot keep all it was sent discards the bytes
past the offset it gives, and holds exactly that many from then on, so
that the next `UPDATE_DATA` begins where its bytes end. Otherwise
the node abandons any update under way, begins this one, and answers 0.
A node keeps an update under way until
it restarts or another begins; it need not keep one across a restart.

**`UPDATE_DATA`** gives the node the bytes of the image from `offset`.
Its answer is `OK` if `offset` is the number of bytes the node holds,
and it then holds `data` too; and `OK` again if `offset` and `data`'s
length end where the node's bytes end, without holding them twice, so
that a client that gave up on the answer to the last can send it again.
Otherwise a node answers `ERROR` 10, as it does with no update under way,
and the client sends `UPDATE_BEGIN` again to learn where to go on from.
Whatever its `offset`, a node MUST refuse empty `data` with `ERROR` 3,
and, with an update under way, `data` that would run past `size`. A client sends `data` of `UPDATE_CHUNK` bytes, all but
the last; a node takes any length.

**`UPDATE_END`** asks the node to run the image. A node that holds fewer
than `size` bytes of it answers `ERROR` 10. One whose bytes' SHA-256 is
not `digest`, or that will not run them, because they are not an image
for its hardware or not one it can check, answers `ERROR` 11 and
discards the update. Otherwise it answers `OK`, then restarts into the
image: the connection drops, and the client starts again. A client that
gave up on an `UPDATE_END` does not send it again, since the node may
be restarting into the image: it waits for the node, and reads
`release` in its `INFO`.

A node keeps everything it holds across an update: its address, its
sessions, contacts, groups, messages and settings, and its Bluetooth
bonds. A node SHOULD go back to the firmware it ran before if the new
image does not start, so that a bad image does not leave it unable to
take another. While an update is under way, the node goes on as at any
other time: it sends news, answers other requests, and is on the air.

Anyone who can drive a node can update it: over Bluetooth, a client
that has [paired](#bluetooth-le). The digest says only that the image
arrived as the client sent it, not who made it.

## Byte streams

On USB serial and TCP, each frame is sent as:

| Bytes | Field | |
|---|---|---|
| 2 | magic | `0xF5 0x54` |
| 2 | `length` | the frame's length, 2 to 180 |
| `length` | the frame | |
| 2 | `crc` | CRC-16 of `length` and the frame |

`crc` is CRC-16/IBM-3740: polynomial `0x1021`, initial value `0xFFFF`,
neither input nor output reflected, no final XOR. Its check value, over
the ASCII bytes `123456789`, is `0x29B1`.

`0xF5` cannot occur in UTF-8, so no byte of a node's console text, nor
of anything a person types into it, starts a frame.

**Finding frames.** A receiver looks for the magic. Where it finds it,
it reads `length`; if that is from 2 to 180, it reads the frame and
`crc`, and if the CRC is right, it has a frame, and looks for the next
magic after it. Otherwise, the `0xF5` is not the start of a frame, and
the receiver looks again from the byte after it. Bytes that are not
part of a frame are text: a client MAY show a node's text as its
console, and a node gives text it receives to its console as if typed.

A receiver holding part of a frame that has received nothing more for
`GAP` milliseconds SHOULD treat its first byte as text and look again
from the byte after it, as for a wrong CRC. A client that went away
mid-frame would otherwise leave the node waiting for the rest, with the
next client's frames read as the end of it.

On a serial port the node's console stays where it was. A node MUST
NOT send news to a serial port until a client has said `HELLO` on it,
nor after the connection has [lapsed](#going-quiet), and so does not
send frames to a terminal that has not asked for them.
A UART runs at 115200 baud, 8 data bits, no parity, one stop bit.

## Bluetooth LE

A node offers one GATT service, with two characteristics:

| | UUID | Properties |
|---|---|---|
| The service | `7a280001-eb17-4c1c-889b-1741dd50ff40` | |
| To the node | `7a280002-eb17-4c1c-889b-1741dd50ff40` | write |
| From the node | `7a280003-eb17-4c1c-889b-1741dd50ff40` | notify |

**Frames.** A client writes one frame to the first characteristic with
each write request. The node sends one frame in each notification on
the second, which the client subscribes to. A notification is the frame
itself, not a prompt to read one, and there is nothing to read. Neither
end splits a frame across writes or notifications, and neither uses
the byte-stream wrapping above: the Bluetooth link already delimits and
checks each.

**MTU.** A frame of 180 bytes needs an ATT MTU of 183. A client MUST
ask for at least that. A node MUST support it, and MUST answer `HELLO`
on a connection whose MTU is less with `ERROR` 7.

**Who may drive the node.** Both characteristics MUST require an
encrypted link from LE Secure Connections pairing with protection
against a man in the middle. The node is paired by passkey entry: a
node with a screen shows a passkey, which the user types into the
client; a node without one uses the passkey set with `SET` 4, and
until one is set, it MUST NOT pair. A client that has paired, and keeps
the bond, may drive the node from then on. A node keeps its bonds until
the user clears them, on the node itself or over USB.

**Advertising.** A node advertises the service's UUID, so a client can
find it. It MUST NOT advertise its address, its routing id or anything
derived from them, nor the user's name for it.

A node MAY add a tag to the name it advertises, so that a user with
more than one node can tell them apart before pairing. The tag MUST
be drawn wholly at random, at least 16 bits of it, and carry nothing
else: nothing from the node's address, routing id or keys, nor any
other value that stays the same, such as a serial number. A node MUST NOT keep a tag past the
Bluetooth address it was advertised with: one whose address changes
from time to time draws a new tag, independently of the last, with each
address, and one whose address is fixed keeps its tag until it is
erased. A node with a screen that advertises a tag SHOULD show it.

## Parameters

| Name | Value | |
|---|---|---|
| `MAX_FRAME` | 180 bytes | |
| `ANSWER_WAIT` | 5 s | |
| `IDLE` | 20 s | |
| `LAPSE` | 60 s | three times `IDLE` |
| `GAP` | 500 ms | |
| `REFS` | 16 | |
| `QUIET` | 10 s | |
| `UPDATE_CHUNK` | 172 bytes | the most `data` an `UPDATE_DATA` carries: a multiple of four that fits a frame, which is then 179 bytes |

## Conformance

An implementation conforms to this section if, for
[`vectors/companion.json`](../vectors/companion.json):

* **crc_check:** its CRC of `input` is `crc`;
* **frames:** it builds `frame` from `type`, `seq` and `fields`, and
  reads them from it; and it wraps `frame` as `stream` for a byte
  stream, and finds `frame` in `stream`;
* **extended:** it reads `fields` from `frame`, ignoring the bytes
  after them;
* **rejected:** as a client, it discards or ignores `frame`; as a node, it
  answers a frame whose `type` is a request's with `ERROR` and the code
  `answer`, and does not answer one whose `answer` is `null`;
* **unknown_to_older:** speaking `version`, it takes `frame` as of a
  type, or naming a setting, its version does not define: as a node,
  it answers `ERROR` with the code `answer`; as a client, it ignores
  news, and discards an answer, whose `answer` is `null`;
* **streams:** given the bytes of `stream` as they arrive, it finds
  the frames and the runs of text in `items`, in that order, and holds
  `pending` waiting for more;
* **group_ids:** from `group_secret`, it works out `group`;
* **exchange:** as a node holding what the exchange shows, given the
  client's frames in order, it sends the node's, in order. This checks
  that an answer carries its request's `seq`, and that news is counted
  from 0 after `HELLO`, through a sync and after it. The `ASKED` in it
  is the node refusing first contact from the address it names. The
  group it makes has the secret `made`, which in use the node draws;
  the `INVITE` it receives is to the group whose secret is `invited`;
  and the `GROUP_MESSAGE`, `POSITION` and second `CARD` it receives,
  and the card it forgets, come when the file says. Its last
  `JOIN_LINK` is a join code whose `check` fails;
* **older:** for each of its connections, as the same node, given the
  frames of a client of the `version` given, it sends the node's, in
  order. The node refuses the same first contact and sends a client of
  version 0 no `ASKED`; it receives the same invite and group message
  and sends a client of version 1 neither, and refuses that client a
  request its version does not define; it answers a client of
  version 2's `SYNC` with a `SYNCED` without `news`, and gives a
  client of version 3 or earlier an `INFO` without `board` and
  `release`; it refuses a client of version 3 an update; and it sends
  a client of version 4 or earlier no position or sharing, and refuses
  a client of version 4 `SHARE`; and it sends a client of version 5 or
  earlier no card, and a `SELF` without `cards` and `card_name`, and
  refuses a client of version 5 `SET` 5; and refuses a client of
  version 6 `JOIN_LINK`;
* **update:** as a client, given the `image` to send and the node's
  frames in order, it sends the client's frames of each of the two
  connections in `update`, in order, going on in the second from the
  offset the node gives; and as a node that runs any image whose
  digest is right, given the client's frames in order, it sends the
  node's, the second connection's after the first's link was lost. The
  node's frames in `refusals` are those of a node given the client's,
  on one connection.

What a node holds, and so which news it sends and when, depends on the
rest of the node, and is checked by running a client against it. The
Bluetooth requirements are checked with a Bluetooth client.

## Rationale

**Why fields by hand, and not a schema language.** The radio frames
are written field by field, and a node that implements them can write
these the same way, with no generator, no runtime and no allocation.
Protocol Buffers, which Meshtastic's companion link uses, would need a
compiler in every client's build and a decoder on the node for a
handful of fixed records. CBOR, which [first contact](first-contact.md)
already carries, would mean a general decoder where EDHOC needs only
fixed byte strings. What a schema buys is growth without breaking, and
the two rules here buy most of it: a receiver ignores bytes past the
fields it knows, and a client ignores news it does not know.

**Why a group has an id, and a client never its secret.** A client
has to name a group to the node, and the node to a client. The secret
would do, and would put on every `SEND_GROUP`, over a Bluetooth link
and into every browser's storage, the one thing that lets anyone read
the group. The id is derived from the secret one way, so it is the
same on each of a user's nodes, and a client that kept a group's
history under it finds the group again after joining it afresh. Eight
bytes are enough to tell a node's few groups apart.

**Why a join code passes through the client anyway.** A join code is
the secret, and the person joining has it on a phone: scanned, or sent
to them. A node has no camera, so the code reaches it through a client
or not at all, and the client of the person sharing it shows it on a
screen the node does not have. What the rule above protects against is
the secret on every request and in every client's storage, and that
is kept: the code crosses the link once, when the user asks, as text
the client shows or hands on, and is not kept. It is the link and not
the secret that goes in the frame so that a client has nothing to
build or read: one that shows a QR code of the text, or passes on what
the camera read, is right without knowing what is in it, and the node,
which reads an address's link already, reads this one too.

**Why group messages and invites are records of their own.** A
`MESSAGE` with a group's id and a writer added would have been one
frame type for everything in a conversation. It would also have been
188 bytes at its longest, past the 180 a node's buffer and a Bluetooth
link's MTU are sized for, and a client of version 1 would have read it
as a message from an address of zeros. As types of their own, a group
message has no need of the 32-byte address, and an older client is not
sent them, by the rule it already relies on.

**Why an invite waits for the user.** A node that took every group it
was invited to would let any contact fill its few places for groups,
and have it relay nothing more than it already does but show the user
conversations they never chose. The invite is held, shown, and taken
only by `JOIN`.

**Why the node keeps the names.** The node's own screen shows who a
message is from, and a user may drive one node from a phone and a
laptop. A name kept on one client is missing on the node and on the
other. Kept on the node, it is in one place, and still never on the
air, which is what "local" in the firmware's interface draft has to
mean: kept by the user's own equipment.

**Why `SYNCED` carries the count.** A sync's last news frame is the
one a client cannot find missing: the count shows a gap only when the
news after it arrives, and `SYNCED` is an answer, numbered by the
request. A client that took the `SYNCED` as the end of a whole list
would forget a contact, group or neighbour whose record was the one
lost, and on a quiet node nothing might come to show it. On a byte
stream a frame can be lost so, its CRC wrong. With the count in the
`SYNCED`, the client knows at once. It is a field and not a news
frame of its own, so a sync costs no frame more.

**Why the node rounds a position, and not the client.** A user may
share a town with a group and a street with a friend, and change
either from a phone or a laptop. If each client rounded, each
`SET_POSITION` would carry a position for every destination, and a
client that rounded wrongly would put it on the air. The node holds the
choices, as it holds the names, so it is the one place that has to get
the grid right, and it is checked against
[the vectors](../vectors/positions.json). The exact position goes no
further than the node, over a link that is already encrypted and
paired.

**Why received positions are records, not messages.** A map shows
where each person is now, not a history. A record for each sender,
which the next replaces, is that; a message for each position would
fill a node's store with a day of one person's walk.

**Why a card is a record, and carries no number or signal.** Who is
about is a list a client shows, as neighbours and positions are, so a
card held is a record that the next from the same address replaces,
and a sync sends them all. A card's `number` is a counter, which
[goal 1](#goals) keeps from clients: the node has already used it to
refuse an older card. [Presence cards](cards.md#receiving) has a node
keep a card's number, what it said and when it was heard, and no
signal: a card heard through a relay says nothing of how near its
sender is. `heard` is a `u32` and not a `NEIGHBOUR`'s `u16`, because a
card is held for [`CARD_KEPT`](cards.md#parameters), a day, which is
longer than `0xFFFF` seconds.

**Why a card becomes a contact by `SAVE_CONTACT`.** Saving a contact is
already what lets an address in and gives it the user's name; a frame
of its own would do the same with a card's address in it. The card's
name is not taken as the contact's, since it is a claim its sender
made and the contact's name is the user's.

**Why the card's name is a setting of its own.** It is the one name a
node puts on the air in clear. Every other name a client gives the
node is kept for the user, and goes on the air, if at all, only in an
invite, sealed: a setting that is nothing but what cards carry keeps
the two from being mixed up.

**Why a record, and not a change.** A record says the whole of one
thing, so a client that applies records in order is right after each,
whatever it missed before. News that said what changed would leave a
client that missed one wrong until it next synced, and unaware.

**Why a CRC on byte streams.** The serial port carries the console as
well, and boot messages from the chip's ROM, at another baud rate, read
as noise. Without a check, a `0xF5 0x54` in that noise followed by a
large length would swallow the real frames after it. With one, the
receiver finds out and looks again. Meshtastic and MeshCore, by their
public documentation, frame with a marker and a length and no check.

**Why `0xF5`.** It is never a byte of UTF-8, so console text, in any
language, cannot start a frame. `0x54` is `T`.

**Why 180 bytes.** A Bluetooth notification carries at most the MTU
less 3 bytes. Phones agree to MTUs of 185 and more, so frames of 182
bytes or less go in one notification without the protocol fragmenting
them; 180 leaves two spare. The longest frame, a `MESSAGE` with 128
bytes of text, is 176.

**Why notifications carry the frame.** The other shape, a notification
that only prompts the client to read, costs a round trip for each frame
and a characteristic more, and buys a frame longer than a notification.
At 180 bytes nothing needs to be longer.

**Why 128 bytes of text.** It fits a `MESSAGE` in a frame with room to
add fields, and is about what other meshes allow in one LoRa frame.
The radio protocol does not yet say what a message's plaintext holds
([Not yet specified](#not-yet-specified)), and the limit follows
whatever it does.

**Why one request at a time.** A node then needs room for one request,
and a client needs no table of what is outstanding. A client that
wants to send several messages sends them one after another; each
answer comes as soon as the node has the message, not when it is on
the air.

**Why `ref`.** A `SEND` whose answer was lost is the one request that
cannot simply be sent again: the user would see a message twice. With
`ref`, sending again is safe, and a client never has to ask whether
the first try arrived. The text is part of the match so that two
clients whose `ref`s happen to agree cannot lose a message: at worst,
the same words to the same node at once go as one.

**Why a client pings while news arrives.** Over USB serial, a node
cannot see a client leave. Without a request now and then, it would
send news for ever to whatever opened the port next, a terminal
included. A node that stopped on its own, with no rule for the client,
would cut off a client that was only listening, and that client would
see nothing wrong: no news looks like nothing happening. A ping every
`IDLE` seconds costs eight bytes, and `ERROR` 6, which a client already
handles, tells one that was cut off to start again. `LAPSE` is three
pings, so one lost to a busy port does not end a connection. Both are
counted from an answer, not a request: a client may not ask again
while a request is unanswered, and a long sync is one request.

**Why saving a contact lets a node in, and not a request to accept.**
A node cannot hold a handshake open while a person decides: its frames
are sent again only for seconds. So the answer has to be there before
the node asks again, and it has to name the node, or whoever asked
next would be let in instead. A saved contact is both, it is already
what a user does with an address they mean to talk to, and it holds
after a restart. `ASKED` comes only after the handshake's third
message, so the address in it is one the asking node has proved, not
one it claimed.

**Why the other node is not told a session ended.** Telling it needs a
frame on the air that only the session's two ends can make, and the
radio protocol has none yet. Until it does, ending a session is what a
node does with its own keys.

**Why a random tag in the name.** With every node named alike, a user
with several of them nearby cannot tell from a phone's list which one
is which. A tag taken from the address would tell them, and would also
tell anyone in range which mesh node it was. A tag drawn at random says
nothing about the node's mesh identity. Kept from day to day, it lets
a node be recognised, but no more than a fixed Bluetooth address
already does; a node that changes its address so as not to be followed
would be undone by a tag that stayed the same, so a new tag is drawn
with each address. A new draw that happens to equal the last tells an
observer no more than two different nodes that happen to match, so it
is not drawn again. Sixteen bits makes two nodes in one place alike about once
in 65,000. A name the user chooses was the other way, and would say who
the node belongs to.

**Why the passkey, and not "just works" pairing.** A node may relay
for its neighbours on a hill, and anyone who can drive it can read its
messages and change its region. Passkey entry stops someone in range
from pairing unseen. A node with no screen has no way to show one, so
its passkey is set over USB, which needs the node in hand.

**Why nothing derived from the address in advertisements.** The radio
protocol keeps a node's address out of the clear. A Bluetooth
advertisement that carried it would tell anyone in range which mesh
node they were near, and follow it about.

**Why an update is the companion protocol's own.** A node's radio
firmware is what a phone that drives it most often has to change, and
the link to it is already open, paired and checked. A second Bluetooth
service, as some meshes offer, would need its own pairing rules and its
own client code in every app, and would not work over USB. One request
at a time is slower than a stream of writes, about four minutes for an
image of a megabyte over Bluetooth, and is what lets a node of any size
take an update with the one buffer it already has.

**Why a digest, and an offset from the node.** A link drops part of the
way through an image of thousands of frames more often than not on a
walk away from the node. With the node saying how much it holds, a
client goes on from there, and never has to know what became of the
last frame it sent. The digest is what lets a node tell the image it
holds part of from another of the same size, and check the whole
before running it, whatever the link did to it.

**Why the board in `INFO`.** `firmware` is for a person, and a client
must not decide from it. An image built for other hardware does not
start, at best, so a client needs a name it can match to choose one,
and a node needs a way to say it cannot be updated at all.

## Not yet specified

* **Who is in a group.** A node does not know, and nor does a client:
  it sees the routing ids that have written.
* **The airtime budget**: `reason` 4 names it, and `AIRTIME` gives only
  the region's limit. The budget's fields come with its section.
* **What a message carries on the air**: its text, its time, whether it
  is UTF-8. This section's `text` is what the user wrote, and the limit
  of 128 bytes is provisional until that is said.
* **A short code to compare addresses**, the same in every
  implementation: proposed, with how an address is written in a link
  and a QR code, in [sharing.md](sharing.md).
* **Sessions with addresses that are not contacts**: `CONTACT` says
  whether a contact has a session, and nothing lists the others.
* **Telling the other node** that a session has ended, so that it need
  not find out by having no answer.
* **Authentication over TCP.** The framing above serves TCP, but
  nothing yet says who may drive a node over a network. Until something
  does, a node SHOULD NOT offer this protocol on a network socket.
* **A node's own fix**, for a node with a satellite receiver to tell
  its clients where it is.
* **What became of a position** sent: whether it went, and whether a
  contact acknowledged it.
* **Developer frames**: routes, links and counters for whoever is
  debugging the mesh, which the console shows today.
* **Signed firmware**: an image a node checks was made by whoever
  publishes its firmware, not only that it arrived whole.
* **Sleeping leaves**: what a client sees of a node that is off the
  air most of the time.
* **How many cards a sync sends.** A node in a crowd may hold a day of
  cards, and each is a frame of a sync. A node holds what it has room
  for, and nothing yet lets a client ask for fewer.
