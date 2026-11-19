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
| `0x06` | `OFF` | | `OK` |
| `0x10` | `SEND` | `ref` `u32`, `to` `addr`, `text` `str` up to 128 | `QUEUED` |
| `0x11` | `READ` | `through` `u32` | `OK` |
| `0x12` | `FORGET` | `contact` `addr`, `through` `u32` | `OK` |
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
| `0x28` | `FORGET_GROUP` | `group` `gid`, `through` `u32` | `OK` |
| `0x30` | `UPDATE_BEGIN` | `size` `u32`, `digest` `digest`, `signature` `bytes` up to 64 | `UPDATING` |
| `0x31` | `UPDATE_DATA` | `offset` `u32`, `data` `bytes` up to 172 | `OK` |
| `0x32` | `UPDATE_END` | | `OK` |
| `0x33` | `SET_POSITION` | `lat` `i32`, `lon` `i32`, `altitude` `i16`, `accuracy` `u16`, `age` `u16` | `OK` |
| `0x34` | `SHARE` | `contact` `addr`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` | `OK` |
| `0x35` | `SHARE_GROUP` | `group` `gid`, `precision` `u8`, `fields` `u8`, `interval` `u16`, `minutes` `u16` | `OK` |
| `0x36` | `UPDATE_BOOTLOADER` | | `OK` |
| `0x37` | `WIPE` | | `OK` |

Any request may instead be answered by `ERROR`.

### Answers

| `type` | Answer | Fields |
|---|---|---|
| `0x40` | `OK` | |
| `0x41` | `ERROR` | `code` `u8` |
| `0x42` | `INFO` | `version` `u8`, `firmware` `str` up to 31, `board` `str` up to 31, `release` `str` up to 31, `update` `u8` |
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
a client cannot update the node; `release` is the version
of that firmware, as [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
writes one, without a leading `v`, and is empty if it has none, as a
build made by hand may not. `update` says how a client gives the node
new firmware: 0 if it cannot, 1 over this protocol, and 2 by the node's
bootloader ([Updating the firmware](#updating-the-firmware)).

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
| `0x80` | `SELF` | `address` `addr`, `role` `u8`, `region` `str` up to 15, `power` `i8`, `time` `u32`, `cards` `u8`, `card_name` `str` up to 31, `most` `u8`, `pairing` `u8` |
| `0x81` | `CONTACT` | `address` `addr`, `session` `u8`, `name` `str` up to 31, `wake` `u16` |
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
| `0x94` | `FIX` | `receiver` `u8`, `source` `u8`, `lat` `i32`, `lon` `i32`, `altitude` `i16`, `accuracy` `u16`, `age` `u32`, `satellites` `u8` |
| `0x95` | `SLEEP` | `wake` `u16`, `listen` `u8`, `state` `u8`, `keeper` `u32`, `retry` `u16` |
| `0x96` | `FORGOTTEN` | `contact` `addr`, `through` `u32` |
| `0x97` | `GROUP_FORGOTTEN` | `group` `gid`, `through` `u32` |

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
them. `most` is 1 if `power` is [the most](#the-requests) the node may
transmit at, as the node works it out, and 0 if it is a power the node
was given. `pairing` says how the node is [paired](#bluetooth-le): 0 if
it shows a new passkey for each pairing, 1 if it has no screen and
pairs with the default passkey, and 2 if it pairs with a passkey set
with `SET` 4. A client that sees 1 SHOULD offer the user to set a
passkey of their own.

**Contacts** (`CONTACT`). A contact is an address the user has
saved, with a name. `session` is 1 if the node shares a session with
it ([First contact](first-contact.md)), 0 if not. The name is the
user's, for the user: it is kept on the node and given to clients, and
a node MUST NOT send it on the air. `wake` is how long the contact
said it [sleeps](sleeping.md#telling-the-source) between wakes, in
seconds, in the session the node shares with it: 0 if it said it does
not sleep, if it has said nothing, or if there is no session. A message
to a contact whose `wake` is not 0 waits with its keeper until the
contact next wakes, and may stay sent for as long, and longer for each
try ([Waiting longer](sleeping.md#telling-the-source)); a client SHOULD
say so where it shows the message, so that the user does not take it
for lost.

**Messages** (`MESSAGE`). Each has an `id`, given by the node: it is
at least 1, unique on the node and greater than every `id` before it,
so a client can ask for those after one it holds. `contact` is the address the
message went to or came from, whether or not it is a saved contact.
`time` is when it was written or received, by the node's clock. `flags`
bit 0 is set once a received message has been [read](#the-requests); the
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
| 4 | the node's [airtime budget](airtime.md) |
| 5 | the radio: other frames go first |

[The airtime budget](airtime.md#what-a-client-is-told) says which of 3
and 4 a message waiting for both is given.

`wait` is the node's estimate, in seconds, of how long until it goes,
0 if it has none, and at most `0xFFFF`.

**Forgotten** (`FORGOTTEN`, `GROUP_FORGOTTEN`). How much of a
conversation the user has [forgotten](#the-requests): for an address,
every `MESSAGE` and `INVITE` with that `contact`, and for a group, every
`GROUP_MESSAGE` to it, whose `id` is `through` or less. The node holds
none of them, and a client holds none either once it has the record: a
client that receives one MUST forget every such message and invite it
holds, whatever its state and wherever it keeps it. A record holds for
the address or group whether or not it is a contact or a group the node
holds, and its `through` only ever grows. Messages after it are kept as
any others are.

A node keeps these records across restarts, at least `FORGOTTEN_KEPT`
of them. One with no room for another drops the record with the least
`through`; a client that has not had it by then keeps what it held of
that conversation, and the node has forgotten it all the same.

**Neighbours** (`NEIGHBOUR`). The nodes whose announces the node hears,
by routing id. `role` is as in `SELF`. `snr` is the signal-to-noise
ratio of the last frame heard from it, in quarters of a dB. `heard` is
how many seconds ago that was, up to `0xFFFF`, as of when the record
was sent. A client knows a neighbour's address only if it can match the
routing id to one, by working out the [routing id](routing.md#routing-ids)
of each address it knows: a key blinded from the address, one scalar
multiplication in the Ed25519 group, and a hash, which a client can
keep with the address rather than work out again.

**The air** (`AIRTIME`). The region's limit on transmitting, as the
node is spending it. `period` is the length of the period the profile
limits, in seconds, 0 for a profile with no limit. `allowed` is the
time on air the profile allows in a period, and `used` how much of it
the node has used in the period ending now, both in milliseconds.
`wait` is how many milliseconds until the node could send its longest
frame, 0 if it could now. A profile with no limit gives `allowed` and
`wait` as 0.

**Sleeping** (`SLEEP`). Whether the node, as a
[leaf](routing.md#roles), [sleeps](sleeping.md): turns its radio off
between the times it listens, to save its battery, while a relay keeps
its messages for it. `wake` and `listen` are what `SET` 8 and 9 set:
`wake` is `w`, the longest the node lets pass between its polls, in
seconds, or 0 if it is not to sleep; `listen` is `l`, how long it
listens after each poll, in seconds. `state` is what it does now:

| `state` | | |
|---|---|---|
| 0 | **awake**: it listens all the time | `wake` is 0, or the node is a relay, which never sleeps |
| 1 | **asleep**: it sleeps, and `keeper` is its keeper's routing id | |
| 2 | **waiting**: it is to sleep, but listens all the time until it has a relay it can take as keeper: it is [starting](routing.md#starting), or hears no relay it may use | |
| 3 | **resting**: it is to sleep, but the relays it could take have not answered its polls ([A relay that does not keep](sleeping.md#changing-keeper)), so it listens all the time; `keeper` is the relay it will try again, in `retry` seconds | |

`keeper` is 0 in states 0 and 2, and `retry` is 0 in every state but
3, and at most `0xFFFF`. A node that sleeps keeps its link to its clients as it would
awake: only its LoRa radio sleeps. A message it sends goes at once,
but its acknowledgement waits with the keeper until it next polls, so
it may stay sent for up to `wake`.

**Power** (`POWER`). `millivolts` is the battery's voltage, 0 if the
node cannot measure it. `percent` is the node's estimate of the charge
left, 255 if it has none. `flags` bit 0: the battery is charging. Bit
1: the node is running from external power. The other bits are 0.

**What holding a node gives.** A node keeps its identity, the keys of
its sessions, its groups' secrets, its contacts and its messages in its
own flash, and nothing in this section protects them from whoever has
the node in hand: they can read them over its USB port, or by putting
firmware of their own on it. So a node that is lost or taken has given
up its address, its sessions and every group it was in. Its user should
tell their contacts, who should no longer trust that address, and should
make new groups for the people still in them. `FORGET` and
`FORGET_GROUP` erase a conversation from the node while the user still
has it, and `WIPE`
([below](#the-requests)) erases a node that is still in hand, before it
is given away or sent off to be mended. How a node's contacts learn that
its address is no longer its owner's is
[not yet specified](first-contact.md#not-yet-specified).

### Groups

**Groups** (`GROUP`). A [group](groups.md) the node holds, with the
user's name for it. A client knows a group by its **id**, which the
node works out from the group's secret `G`:

```
gid = Expand(G, "tern v0 group id", 8)
```

with `Expand` as in [Secured unicast frames](unicast-security.md#notation).
A node works the id out when it takes the group, and keeps it when the
group's [secret is replaced](groups.md#replacing-the-secret), so that a
client knows the group by one id however many secrets it has had. So
the id is the same on every node that took the group under the same
secret, and gives nothing of any secret away. Like the name, it is for the node and its
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
[what a member claimed](groups.md#receiving): a client MUST show it as
claimed wherever it shows it, a name it knows by that
[routing id](routing.md#routing-ids) included, and MUST NOT show it as
it shows a contact. `time`, `flags` and `text` are as for a
`MESSAGE`.

A group message this node wrote is **waiting** until it has gone on the
air, with `reason` 4 while it waits for
[the node's allowance](flooding.md#the-allowance) or its
[budget](airtime.md#what-a-client-is-told), and **sent** from
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
invite has been [read](#the-requests).

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

**The node's own fix** (`FIX`). Where the node takes itself to be: the
fix it [uses](positions.md#sharing) to share its position, which is the
more recent of its own receiver's and the last a client gave it with
[`SET_POSITION`](#the-requests). It is what a client centres a map on,
and what it shows of the node's receiver.

`receiver` is the node's satellite receiver, as it is now:

| `receiver` | |
|---|---|
| 0 | the node has none |
| 1 | off: [`SET`](#the-requests) 7 turned it off |
| 2 | on, and without a fix |
| 3 | on, with a fix |

Other values are reserved, and a client treats one it does not know as
2. `source` says whose fix the rest of the record is: 0 if the node has
none, 1 if it is the receiver's, 2 if it is one a client gave it. `lat`,
`lon`, `altitude` and `accuracy` are as in `SET_POSITION`. `age` is how
many seconds old the fix was as of when the record was sent.
`satellites` is how many satellites the receiver's fix was made from, 0
if it does not say or if the fix is a client's. A record whose `source`
is 0 has its other fields, but `receiver`, 0.

A fix is the node's own, and goes no further than the node's clients
because of this record: what goes on the air is the
[cell](positions.md#the-grid) each destination is shared, when sharing
is on, and nothing when it is not.

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
already, unless its user has it
[answer no first contact](first-contact.md#responding). A node holds
at most one session with an address: first contact with an address it
shares a session with puts the new session in the old one's place, once
the handshake is complete, and needs no more room, and the old session
is [erased](first-contact.md#erasure) then. That is how two nodes
recover when only one of them still holds their session, and how a
sender [starts a session again](unicast-security.md#starting-again). Whether it takes first contact from any other address is its
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
  removed, gains or loses a session, or tells it a new `wake`;
* `SELF` when anything in it but `time` changes;
* `POSITION` and `GROUP_POSITION` when a position is received, and
  when one is forgotten, with `precision` 0;
* `SHARING` and `GROUP_SHARING` when sharing is turned on, changed,
  turned off or runs out, and, with `precision` 0, when it ends because
  the contact is removed or the group left;
* `NEIGHBOUR_GONE` when the node forgets a neighbour;
* `CARD` when the node accepts a card, and `CARD_GONE` when it forgets
  one;
* `FIX` when its `receiver` or its `source` changes;
* `SLEEP` when anything in it but `retry` changes;
* `FORGOTTEN` and `GROUP_FORGOTTEN` when a `FORGET` or `FORGET_GROUP`
  makes its `through` greater;
* `ASKED` when it refuses [first contact](#who-may-make-first-contact),
  as that section says.

A `minutes`, an `age` or a `heard` that only counts on is not a change.

It SHOULD send `NEIGHBOUR`, `AIRTIME` and `POWER` when they change,
and `FIX` when its fix moves, and MAY send each no more often than once
every `QUIET` seconds, so that a neighbour heard every second, or a
receiver that gives a fix every second, does not fill the link. A fix
moves when its `lat`, `lon`, `altitude`, `accuracy` or `satellites`
differs from the last record's; one that only grows older has not
moved. A `FIX` that the list above requires, for a change of `receiver`
or `source`, is sent at once, however soon after the last.

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
version 16. Version 15 is version 16 without [forgetting](#the-requests):
the requests `FORGET` and `FORGET_GROUP`, and the news `FORGOTTEN` and
`GROUP_FORGOTTEN`. Version 14 is version 15 without [sleeping](#what-the-node-holds):
the settings 8 and 9, the news `SLEEP`, and `CONTACT`'s `wake`. Version 13 is the same in every frame, but its routing ids
were made from the address itself, as [Routes](routing.md#routing-ids)
made them before announces carried a key blinded from it: `SHA-256("tern
routing id" || A)` in place of `B`. Version 12 is version 13 without
[signed images](#signed-images) and [wiping](#the-requests): `UPDATE_BEGIN`'s
`signature` and the request `WIPE`. Version 11 is version 12 without
[updates by the bootloader](#by-the-bootloader): the request
`UPDATE_BOOTLOADER` and `INFO`'s `update`. Version 10 is version 11
without `SELF`'s `pairing`.
Version 9 is version 10 without
[the most](#the-requests): `SET` 3's -128 and `SELF`'s `most`.
Version 8 is version 9 without
[turning the node off](#the-requests): the request `OFF`. Version 7 is
version 8 without
[the node's own fix](#positions): the setting 7 and the news `FIX`.
Version 6 is version 7 without
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
is sent a `SELF` without `cards` and `card_name`. One of version 7 or
earlier is told of no fix. One of version 15 or earlier is told nothing
of what is forgotten: it is sent no `FORGOTTEN` or `GROUP_FORGOTTEN`,
and keeps what it holds of a conversation another client forgot, though
the node sends it none of that again. One of version 14 or earlier is told
nothing of sleeping: it is sent no `SLEEP`, and a `CONTACT` without
`wake`. One of version 11 or earlier is sent an `INFO` without `update`, and
with an empty `board` unless the node is updated over this protocol,
since to such a client a board means that. One of version 10 or earlier is sent a `SELF` without
`pairing`. One of version 9 or earlier is sent a `SELF`
without `most`, and its `SET` 3 of -128 is a power, as its version has
it, that no radio sends at: a node answers it with `ERROR` 3. A node MUST answer a request, or a setting,
that the client's version does not define with `ERROR` 1, as it does
one its own version does not: it could not tell that client what the
request changed. A receiver reads a frame of a type that only a later version defines as
one of a type it does not know, whatever its own version: a node of
version 5 answers a `SHARE` from a client of version 4 with `ERROR` 1,
and a client of version 4 ignores a `POSITION`. Likewise, a node of
version 6 answers a `SET` of setting 5 from a client of version 5 with
`ERROR` 1, and a client of version 5 ignores a `CARD`; and a node of
version 8 answers a `SET` of setting 7 from a client of version 7 with
`ERROR` 1, and a client of version 7 ignores a `FIX`; and a node of
version 9 answers an `OFF` from a client of version 8 with `ERROR` 1,
and one of version 12 answers an `UPDATE_BOOTLOADER` from a client of
version 11 with `ERROR` 1, and one of version 13 a `WIPE` from a client
of version 12, and one of version 15 a `SET` of setting 8 from a client
of version 14, which ignores a `SLEEP`, and one of version 16 a `FORGET`
from a client of version 15, which ignores a `FORGOTTEN`. A client of version 12 or earlier sends `UPDATE_BEGIN`
without a `signature`, and a node that [checks signatures](#signed-images)
refuses it, as it refuses any image that is not signed.
A node of version 14 gives every client the routing ids its radio
uses, whatever the client's version, since it has no others. A client
works out routing ids from addresses as the node's version makes them:
one of version 13 or earlier that makes them from the address itself
matches no routing id from a node of version 14 to an address, and
shows each as one it does not know.
Later versions only add types, settings, error codes and
fields at the end of a frame, so any two versions can talk. A change
that cannot be made that way is a new protocol, with its own magic and
its own Bluetooth service.

A client then, typically, sets the node's clock and syncs:

```
client                         node
HELLO       seq 1, version 10 ─▶
                              ◀─  INFO        seq 1, version 10
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
greater than `after`, in order of `id`, a `FORGOTTEN` for every address
and then a `GROUP_FORGOTTEN` for every group it holds one for, whatever
`after` is, a `NEIGHBOUR` for every
neighbour, a `POSITION` or `GROUP_POSITION` for every position it
holds, a `SHARING` or `GROUP_SHARING` for every contact or group it
shares its position with, a `CARD` for every card it holds, one
`AIRTIME`, one `POWER`, one `FIX` and one `SLEEP`. Then it answers `SYNCED`. News
that a change prompts while it syncs is sent as at any other time,
among the rest.

For contacts, groups, neighbours, positions, sharing and cards, a sync
is the whole list: a client that receives `SYNCED` MUST forget every
contact, group, neighbour, position and card it holds that the sync
did not send, as if it had received its `_GONE` or a position's record with `precision`
0, and take sharing to be off with every contact and group the sync
sent no `SHARING` or `GROUP_SHARING` for. Messages are not: a sync
sends only those after `after`, and a client keeps the rest, but for
those a `FORGOTTEN` or `GROUP_FORGOTTEN` in it covers. A client that
was away when a conversation was forgotten learns it so.

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
news. A client that wants them keeps its own copy. That is not the
user forgetting them: it sends no `FORGOTTEN`, and a client keeps its
copy.

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
| 3 | power | `i8` | the most the node transmits at, in dBm; -128 for the most it may |
| 4 | passkey | `u32` | the [Bluetooth](#bluetooth-le) passkey, 0 to 999999, or `0xFFFFFFFF` for the node's default |
| 5 | cards | `u8` | 1 to send [cards](#cards), 0 to send none |
| 6 | card name | `str` up to 31 | the name the node's cards carry; empty for none |
| 7 | receiver | `u8` | 1 to run the node's satellite receiver, 0 to turn it off |
| 8 | wake | `u16` | `w`: 0 not to [sleep](sleeping.md), or how long the node lets pass between polls when it does, in seconds, from `WAKE_MIN` to `WAKE_MAX` |
| 9 | listen | `u8` | `l`: how long the node listens after each poll, in seconds, from `LISTEN_MIN` to 255 |

A node MUST refuse, with `ERROR` 3, a region it does not have and a
power its radio cannot send at or that would let it radiate more than
its profile allows. A node MAY restart to apply a setting, after it
has answered: the connection then drops, and the client starts again.

A power of -128 is not a power but the most: the most the node's radio
gives that its profile allows into its antenna, as the node knows them.
A node given it MUST transmit at no more than that, and MUST work it
out again whenever its profile changes, or the limits it holds for one
do, as they may with new firmware; `SELF` gives it as `power`, with
`most` 1. A node whose radio gives no power that its profile allows
refuses it with `ERROR` 3. A node that has never been given a power
MAY start at the most, or at a power its maker chooses; `most` says
which.

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

A node with a satellite receiver runs it until it is given `SET` 7
with 0, and again when it is given it with 1, and keeps the setting
across restarts; it MUST refuse any other value with `ERROR` 3. A node
with none answers `OK` to 0, and refuses 1 with `ERROR` 3. Off, a
receiver gives the node no new fix, and the last it gave stays the
node's until a client gives a more recent one: turning it off is how a
user saves the power it draws, which on a small battery is more than
the radio's, and is not a move. Turning the receiver on or off sends
nothing on the air.

A node MUST refuse, with `ERROR` 3, a wake that is not 0 and is
below [`WAKE_MIN`](sleeping.md#parameters) or above `WAKE_MAX`, and a
listen below `LISTEN_MIN`. A node keeps both across restarts. One
that has never been given them does not sleep, and listens for
`LISTEN_MIN`. A node given a wake other than 0 sleeps while it is a
leaf, as [Leaves that sleep](sleeping.md#sleeping) allows: a relay
keeps the setting, and does not sleep by it until it is a leaf again.
Sleeping is a leaf's choice, made for its battery: what it costs is
time, since a message to it waits for it to wake, and a client SHOULD
say so when the user turns it on. A client MUST NOT send `SET` 8 or 9
unless its user asked it to.

**`OFF`** turns the node off. A node MUST answer it with `OK`, and
then turn off: every connection drops, and the node sends and receives
nothing, on the air or on any link, until it is turned on again on the
node itself, by its button, its reset or its power. Nothing in this
protocol turns a node on. A node turns off only once its answer has
gone, so that the client is told, and SHOULD turn off within `QUIET`
seconds of answering. Being turned off and on again is a restart: a
node keeps across it what it keeps across any other.

A client MUST NOT send `OFF` unless its user asked it to, and SHOULD
say before it does that the node can be turned on again only on the
node. A client that has had `OK` to an `OFF` SHOULD NOT try to connect
to the node again until its user asks it to: the node is not there to
answer. One that gave up on the answer may send `OFF` again: it is
not one of the requests [sending twice](#requests-one-at-a-time) can
harm. A node that is already off does not answer, and the client takes
it as gone.

**`WIPE`** erases the node. A node MUST answer it with `OK`, or with
`ERROR` 8 if it cannot erase itself now, and after `OK` MUST erase
everything it holds that this section names and restart as a node that
has never been used: its identity, so that it starts with a new
address; its sessions and every key of them; its contacts, groups and
their secrets, messages, cards and positions; its settings, the
passkey among them; and every Bluetooth bond. It MAY keep the time it
has spent on the air, which a region's limit on transmitting counts
([Profiles](phy.md#profiles)) and which is no secret. Every connection
drops. A node SHOULD erase the storage that held these, not only mark
its records unused, so that a reading of its flash afterwards finds
none of them. As with `OFF`, a node acts only once its answer has gone.

A client MUST NOT send `WIPE` unless its user asked it to, and SHOULD
say first that the node's address, contacts, groups and messages will
be gone for good, and that the node will have to be paired again. A
client that has had `OK` to a `WIPE` forgets its Bluetooth bond with
the node and everything it holds for it: the node it finds next is a
new one.

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

**`FORGET`** forgets the conversation with `contact` through
`through`: every message and invite with that address whose `id` is
`through` or less. A `through` greater than any `id` the node has given
is taken as the greatest it has given, so that a message that comes
later is not forgotten before it is written. The node MUST NOT send a
client any of them again, nor show them on a screen of its own, and
SHOULD erase the storage that held them, not only mark them unused. A
message or invite among them that is waiting or sent is given up first,
as [`END_SESSION`](#the-requests) gives one up: the node sends no frame
of it again. A received invite forgotten takes with it the secret it
carried, and can no longer be joined. The contact, if it is one, is
kept, and so are its session, its position and sharing with it.

The node then makes its `FORGOTTEN` for the address the greater of the
one it holds and `through`, and sends the record to every client. A
`FORGET` that makes it no greater changes nothing, and sends no news.
A node MUST refuse an invalid address, or its own, with `ERROR` 4, and
answers `OK` for an address it holds nothing of, which is not a
contact, or which it never heard of: the conversation may live on in a
client's copy.

A client MUST NOT send `FORGET` or `FORGET_GROUP` unless its user asked
it to, and SHOULD say first that the conversation goes from the node
and from every client of it, for good, and, if any of it is waiting or
sent, that it will not be sent. It gives as `through` the greatest `id`
it shows the user in that conversation, so that a message that arrives
while the user decides is not forgotten unseen. A client that hides a
conversation without forgetting it does so on its own, and tells the
node nothing.

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

**`FORGET_GROUP`** is `FORGET` for a group: it forgets every group
message to `group` whose `id` is `through` or less, and the record it
changes is the group's `GROUP_FORGOTTEN`. One of them waiting is given
up, as `LEAVE_GROUP` gives one up; invites to the group are the
conversation with whoever they went to or came from, and stay. The
group, if the node holds it, is kept. A node answers `OK` for a group it
does not hold, or never held: a group left is the one most likely to be
forgotten.

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
until it is renamed, or its secret is replaced.

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
A client need not give a node whose receiver has a fix its position,
and SHOULD NOT give one that came from that node's own `FIX`: the node
would take its own fix back as a client's.
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

A client can give a node new firmware: an **image**, which is whatever
the node's hardware runs. What an image holds, and where a client finds
one, is the business of the firmware and of whoever publishes it, not
of this section: a client finds one by the `board` and `release` in
[`INFO`](#answers). A node is updated in one of two ways, as `INFO`'s
`update` says: over this protocol, where it has room to hold a second
image beside the one it runs, or by its bootloader, where it has not.
A node whose `board` is empty answers `UPDATE_BEGIN` and
`UPDATE_BOOTLOADER` with `ERROR` 5, as does one that is updated the
other way.

Whoever publishes a node's firmware signs each image, so that a node or
a client can tell an image is theirs, not only that it arrived whole
([Signed images](#signed-images)).

### Over this protocol

An update is three requests:

**`UPDATE_BEGIN`** says that an image of `size` bytes, whose SHA-256 is
`digest`, follows, and gives its `signature`: 64 bytes, or none if the
client has none. A node MUST refuse a `size` of 0 with `ERROR` 3, one
larger than it has room to hold with `ERROR` 5, and then one whose
`signature` does not [verify](#signed-images) over `digest` with
`ERROR` 11, unless it has been set to take images that are not signed.
It checks the signature of every `UPDATE_BEGIN`, one that goes on with
an update under way included, and a refused one leaves any update under
way as it was. It answers
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
bonds. A session is kept as [the secured unicast
frame](unicast-security.md#storage) requires across any restart, with
every counter it has used and every message it has accepted. A node
SHOULD go back to the firmware it ran before if the new image does not
start, so that a bad image does not leave it unable to take another.
Going back MUST NOT take a session back to an earlier state: a node
that would read its sessions in the firmware it goes back to as they
were before the update, not as they are, MUST erase them instead. While an update is under way, the node goes on as at any
other time: it sends news, answers other requests, and is on the air.

Anyone who can drive a node can ask it to update: over Bluetooth, a
client that has [paired](#bluetooth-le). The digest says that the image
arrived as the client sent it; the signature says who made it. A node
that checks signatures takes only images its publisher signed, from
whoever sends them.

### Signed images

A **release key** is an Ed25519 public key (RFC 8032), 32 bytes, of
whoever publishes a node's firmware. The **signature** of an image is
the 64-byte Ed25519 signature (RFC 8032, section 5.1.6, not prehashed)
made with the release key's private key over the 48 bytes

```
message = "TERN-FIRMWARE-V1" || SHA-256(image)
```

where the first 16 bytes are those ASCII characters, and the image is
the file exactly as it is published: for an update over this protocol,
the bytes a client sends, and for one by the bootloader, the package it
is given. A signature **verifies** if it is 64 bytes long and RFC 8032's
verification (section 5.1.7), which refuses an `S` that is not less than
the group order, succeeds over `message` with one of the release keys
the verifier holds.

A publisher SHOULD publish each image's signature beside it, as a file
named as the image with `.sig` after the whole name, holding the 64
bytes and nothing else, and SHOULD publish its release keys where its
users can find them.

A node holds its publisher's release keys in its firmware. A node that
is updated over this protocol MUST check signatures as `UPDATE_BEGIN`
says. It MAY instead be set to take images that are not signed, for
whoever develops its firmware, but MUST NOT be settable so by anything a
client can do over Bluetooth or over this protocol: a node set so takes
an image from anyone who can pair with it. A node holds a short list of
keys rather than one, so that a key can be changed: a release that adds
the new key, then releases signed with it, then one that drops the old.
A node that holds no release key takes no image over this protocol.

A client SHOULD hold the same release keys, and check an image's
signature before it sends the image either way. It MUST NOT send an
image whose signature does not verify, or that has none, unless its
user asks it to after being told that the image may not be the
publisher's; a node that checks signatures refuses such an image
anyway, and one updated by its bootloader does not.

### By the bootloader

A node whose `update` is 2 has a bootloader that takes an image itself,
over Bluetooth LE, and this protocol only asks it to start:

```
client                                 node
UPDATE_BOOTLOADER                 ─▶
                                  ◀─  OK
                                        the node restarts into its bootloader
client ─── the image, by the bootloader's own protocol ───▶ bootloader
                                        the bootloader starts the image
```

**`UPDATE_BOOTLOADER`** asks the node to restart into its bootloader's
update. The node answers `OK`, then restarts: every connection drops,
and the bootloader advertises its own service. What it speaks is the
bootloader's, not this protocol's. A node of this version on an
nRF52840 has a bootloader that speaks Nordic Semiconductor's legacy
DFU over Bluetooth LE (the DFU service of the nRF5 SDK 11, UUID
`00001530-1212-EFDE-1523-785FEABCD123`), and the image for it is a DFU
package of an init packet and the application. The bootloader checks
the image as that protocol has it, writes it and starts it; the node
then answers `HELLO` with the new `release`. A client that sent
`UPDATE_BOOTLOADER` and was not answered does not send it again: it
looks for the bootloader, as the node may be restarting into it.

A node's bootloader writes only its firmware: the node keeps everything
else it holds, as over this protocol.

**While the bootloader waits, anyone in range can install an image.**
The bootloader is not this protocol and holds no bonds, so it takes an
image from whoever connects to it first, not only from the client that
asked, and a node of this version on an nRF52840 checks no
[signature](#signed-images) there: its bootloader checks only the
package's CRC. The window opens only when a client that may drive the
node asks, and lasts until the bootloader has an image or gives up
waiting. A bootloader that, given an image that breaks off part of the
way, waits for another over Bluetooth leaves the node open for as long
as it waits; one that keeps the firmware it had until a new image is
whole, and goes back to it when none comes, closes the window sooner,
at the cost of a cable for a user whose update failed. A node MAY say
its `update` is 2 with either. A client SHOULD check the package's
signature before it sends `UPDATE_BOOTLOADER`, SHOULD send the package
as soon as the bootloader advertises, and SHOULD tell its user that the
node is open to anyone in range until the update finishes.

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
against a man in the middle. The node is paired by passkey entry, with
the passkey set with `SET` 4 or, until one is set, the node's default.
A node with a screen shows its default, a new passkey drawn at random
for each pairing, which the user types into the client. A node without
a screen has the default passkey `123456`, which the user types from
the node's documentation: it MUST NOT pair with any other passkey until
one is set. A client that has paired, and keeps
the bond, may drive the node from then on: connecting again with a bond
is not a pairing. A node keeps its bonds until the user clears them, on
the node itself, over USB, or with `WIPE`.

**Being at the node.** Whoever reads a passkey off the node's screen is
at the node. A passkey that is not shown, the default `123456` or one
set with `SET` 4, says nothing of where whoever types it is, so a node
pairs with such a passkey only in its **pairing window**: the
`PAIR_WINDOW` seconds after it is started by hand, or after its button
is pressed, if it has a button. A node is started by hand when it is
turned on, reset with its reset button or its power, or woken from off
by its button. A restart the node makes itself, to apply a setting, to
run an update, after `WIPE` or after a fault, does not open the window,
so that nothing done over the air or by a client opens it; a node whose
chip cannot tell one start from another opens it at every start. A node:

* MUST NOT begin a pairing with the default passkey `123456` outside its
  pairing window;
* MUST NOT begin a pairing with a passkey set with `SET` 4 outside its
  pairing window while it holds a bond;
* MAY begin a pairing with a passkey it shows on its screen at any time.

A client that cannot pair with a node SHOULD tell its user to press the
node's button, or turn it off and on, and try again within
`PAIR_WINDOW`.

**Advertising.** A node advertises the service's UUID, so a client can
find it. It MUST NOT advertise its address, its routing id or anything
derived from them. It MUST NOT advertise the user's name for it unless
the node sends [cards](#cards), which carry that name on the air
already: then it SHOULD advertise as its card name, cut to fit on a
whole character, so the user can pick it from a list. It advertises
the new name when cards are turned on or off or their name changes.

Otherwise a node MAY add a tag to the name it advertises, so that a user with
more than one node can tell them apart before pairing. The tag MUST
be drawn wholly at random, at least 16 bits of it, and carry nothing
else: nothing from the node's address, routing id or keys, nor any
other value that stays the same, such as a serial number. A node
MUST NOT keep a tag past the Bluetooth address it was advertised with:
one whose address changes from time to time draws a new tag,
independently of the last, with each address, and one whose address is
fixed keeps its tag until it is erased. A node with a screen that
advertises a tag SHOULD show it.

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
| `PAIR_WINDOW` | 180 s | how long after a start by hand, or a press of the button, a node pairs with a passkey it does not show |
| `UPDATE_CHUNK` | 172 bytes | the most `data` an `UPDATE_DATA` carries: a multiple of four that fits a frame, which is then 179 bytes |
| `FORGOTTEN_KEPT` | 16 | the fewest `FORGOTTEN` and `GROUP_FORGOTTEN` records a node keeps |

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
  `JOIN_LINK` is a join code whose `check` fails. The node becomes a
  leaf and is set to sleep, and its neighbour, a relay, becomes its
  keeper when the file says. Its last request is `OFF`, which it
  answers before it turns off;
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
  version 6 `JOIN_LINK`; and sends a client of version 7 no `FIX`, and
  refuses it `SET` 7; and refuses a client of version 8 `OFF`; and
  sends a client of version 11 an `INFO` without `update`, and refuses
  it `UPDATE_BOOTLOADER`; and refuses a client of version 12 an update,
  which carries no signature, and `WIPE`; and sends a client of
  version 14 no `SLEEP`, and refuses it `SET` 8; and refuses a client
  of version 15 `FORGET`;
* **signatures:** given `release_key` and `digest`, it builds
  `message`, and takes `signature` as verifying exactly when `verifies`
  is true. A conforming client and a conforming node both do this;
* **update:** as a client, given the `image` to send, its
  `image_signature`, and the node's frames in order, it sends the
  client's frames of each of the two connections in `update`, in order,
  going on in the second from the offset the node gives; and as a node
  that holds `release_key` as its one release key and runs any image
  whose digest is right, given the client's frames in order, it sends
  the node's, the second connection's after the first's link was lost.
  The node's frames in `refusals` are those of a node given the
  client's, on one connection;
* **bootloader:** as a node that is updated by its bootloader, and has
  no room for an image itself, given the client's frames of each of
  the connections in `bootloader`, it sends the node's, and restarts
  into its bootloader after the first connection's last frame;
* **wipe:** as a node, given the client's frames in `wipe`, it sends
  the node's, and erases itself after the last;
* **forget:** as a node holding what `forget` shows, given the client's
  frames of each of its connections in order, it sends the node's. The
  message it receives in the first comes when the file says; the second
  is a client that was away, and is told what the first forgot.

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

**Why the node tells its clients its own fix.** A client that drives
a node with a receiver of its own, from a phone that is not sharing, or
a computer with no idea where it is, has nowhere to centre a map, and
a user who carries the node in a pack and the phone in a pocket wants
the two to agree. The node already holds the fix it shares from, so
the record is that fix, whoever made it: a client that showed only the
receiver's would show the user somewhere the node is not sharing from.
`receiver` is there besides, because a receiver that has not yet found
the sky is the thing a user with a fresh board asks about first, and
`satellites` is how a client says how far it has got. The fix goes no
further than the paired link it was already allowed over: `SET_POSITION`
carries the same fix the other way.

**Why `FIX` is a record of its own, and not part of `SELF`.** A
receiver gives a fix every second, and `SELF` is sent whenever any of
it changes: a moving node would send its 32-byte address again with
every step. As a record of its own, sent at most every `QUIET` seconds
as `POWER` is, a walk costs a frame of 21 bytes every ten seconds.

**Why a receiver is on until it is turned off.** Someone who buys a
board with a receiver on it expects it to find where they are; one
that sat unpowered until a client found the setting would look broken.
It puts nothing on the air by itself: sharing is still off for every
destination until the user turns it on. What it costs is power, so
turning it off is a setting a client offers, kept on the node as the
region is.

**Why a client can turn a node off.** A node rides in a pack, sits
on a shelf or is taped to a pole, and the button that turns it off is
small, often recessed, and held for seconds with nothing printed to say
so. The phone in the user's hand is the thing they can reach and read.
It asks nothing new of who may drive a node: anyone who can already
update its firmware or end its sessions can stop it more thoroughly
than this.

**Why off, and not asleep.** Off is the least a board draws, with the
radio and every link down, and nothing listening for a client: that is
what someone putting a node away for a week wants, and why nothing here
can turn it on again. A node asleep for a while, still able to wake on
its own, is a different thing with a different cost, and goes under
[Not yet specified](#not-yet-specified); a later version can give
`OFF` a field for it at the end of the frame.

**Why `OFF` is answered first.** A connection that drops with no answer
looks the same as a node that crashed, ran flat or went out of range,
and a client that cannot tell them apart keeps trying to reconnect to
a node that is off. With `OK` first, the client knows the drop is the
one it asked for, and can tell the user so.

**Why the most is the node's to work out.** What a node may radiate
depends on its radio, its antenna and its profile, and only the node
knows all three: a client that asked for the most by sending a number
would have to know the antenna, and the number it sent would stay
behind when the law, or the profile's reading of it, changes. So a
node that ships at the most and a user who wants it back there say the
same thing, and new firmware that changes a profile's limit moves
every node set to the most with it. A user who sets a number keeps it,
since that is a choice the user made. -128 dBm is far below anything a
radio sends at, so a version-9 node refuses it as an ordinary power,
and no setting is added for one value. `most` is in `SELF`, not a guess
from `power`, because a client cannot tell the most from a number that
happens to equal it, and a user should see which they chose.

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
in 65,000. A name the user chooses would say who the node belongs to,
so a node advertises one only when the user has already chosen to say
so on the air, in its cards, which reach further than Bluetooth does.

**Why the passkey, and not "just works" pairing.** A node may relay
for its neighbours on a hill, and anyone who can drive it can read its
messages and change its region. Passkey entry stops someone in range
from pairing unseen. A node with no screen has no way to show one.
Requiring its passkey to be set over USB first kept a stranger out, but
also kept out every user without a computer, so such a node pairs with
a default printed in its documentation, as many such devices do, and
says so in `SELF`'s `pairing`, so the client can ask the user to choose
another once they have paired. Until they do, anyone in range who knows
the default can pair with it while its [pairing window](#bluetooth-le)
is open, and only then.

**Why nothing derived from the address in advertisements.** The radio
protocol keeps a node's address out of the clear unless its user turns
[cards](cards.md) on: announces carry a key blinded from it
([Routes](routing.md#routing-ids)), not the address. A Bluetooth
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

**Why some nodes hand an update to their bootloader.** An update over
this protocol needs room for a second image while the first runs. An
nRF52840 has a megabyte of flash, its bootloader and Nordic's
SoftDevice keep a fifth of it, and a node's firmware is more than half
of what is left: there is no room for two. Its bootloader can take an
image itself, over Bluetooth, the way the boards' makers ship it, and
Nordic's libraries for Android and iOS speak that protocol. So this
protocol only asks the node to start it, and what makes an update over
the companion link worth having, the open, paired link, is kept for
the asking: no client that may not drive the node can start one. The
cost is the bootloader's protocol in the app beside this one, and a
window in which the bootloader takes an image from anyone in range.
Some bootloaders, given an image that breaks off, wait for one by
cable only; a node on one says it cannot be updated, so that a client
offers the cable rather than an update that stalls.

**Why a digest, and an offset from the node.** A link drops part of the
way through an image of thousands of frames more often than not on a
walk away from the node. With the node saying how much it holds, a
client goes on from there, and never has to know what became of the
last frame it sent. The digest is what lets a node tell the image it
holds part of from another of the same size, and check the whole
before running it, whatever the link did to it.

**Why a version for routing ids made differently.** No frame changed,
but what a client does with three of them did: a routing id in
`NEIGHBOUR`, `GROUP_MESSAGE` or `GROUP_POSITION` is matched to a name
only by working it out from an address, the client's side. A client
that knows from `INFO` which way the node makes them can do either,
for nodes of either age.

**Why the board in `INFO`.** `firmware` is for a person, and a client
must not decide from it. An image built for other hardware does not
start, at best, so a client needs a name it can match to choose one,
and a node needs a way to say it cannot be updated at all.

**Why images are signed.** Pairing says who may drive a node, and a
digest that an image arrived whole; neither says who made it. An image
from a look-alike download page, or one an attacker who paired with the
default passkey sends, is as whole as any. Firmware is everything a node
is: whoever installs their own reads every key it holds, and can make it
anything, a beacon that follows its owner or a jammer. A signature by
the publisher's key is the one check that ties an image to its
publisher, and it costs a node only a check it already has the code
for, since addresses are Ed25519 keys.

**Why over the digest, and with a prefix.** The digest is in
`UPDATE_BEGIN` already, so a node can check the signature before a byte
of the image arrives, and refuse in a second what would otherwise take
four minutes to send, and it needs no second pass over an image it has
already hashed. Signing the digest rather than the image keeps the
signature the same wherever the image is checked, a browser, a phone or
a node, each of which hashes the file anyway. The prefix keeps the key
from being made to sign anything that reads as an image's message by
accident, and names the format, so a later one can differ.

**Why the signature is checked at `UPDATE_BEGIN`, and on every one.**
`UPDATE_END` checks that the bytes are the digest's, and the digest is
what was signed, so checking the signature at the start loses nothing.
Checking on every `UPDATE_BEGIN`, a resumed one too, keeps the rule one
sentence long and asks a node to remember nothing about who began an
update. A refused one leaves an update under way alone, so that a
stranger's bad `UPDATE_BEGIN` cannot throw away the owner's progress.

**Why `bytes`, and not a field of 64.** An empty `signature` says
plainly that the client has none, as a developer with an image of their
own does, and a node set to take such images reads it so. A field that
had to be filled would have needed a value that means none.

**Why a list of keys.** A key held only in a release workflow may have
to be replaced: lost, or exposed. With one key compiled in, the next
image would have to be signed by the old key to be taken at all. With a
short list, a release that adds the new key is signed by the old, and
those after it by the new.

**Why the bootloader is not covered.** A node updated by its
bootloader never has the image pass through it: the bootloader takes it
straight from the client, and checks only its CRC. A check in the node
before it restarts into the bootloader would check nothing that the
bootloader then takes. Only a bootloader that checks signatures closes
that, and replacing a bootloader in the field can leave a board that
only a debugger mends, so this version says what the window is rather
than pretend it is shut. The signature still lets an honest client
refuse a tampered package before it starts the update.

**Why a pairing window.** A passkey that everyone knows is no check on
who pairs: anyone in range who knows `123456` could pair with a node
without a screen and then drive it, read its messages, and update it.
A node cannot tell the owner's phone from a stranger's, but it can tell
when someone has just touched it. So a passkey that is not shown is
taken only for a few minutes after a start by hand or a press of the
button, which the owner, setting a node up, does anyway, and a stranger
across a field cannot. Once a node has a bond, a set passkey is held to
the same rule, so that a passkey that leaks, or is guessed, does not let
a stranger add themselves to a node the owner has left on a hill. A
passkey shown on the screen needs no window: reading it is being there.
Three minutes is long enough to find an app and type six digits, and a
start the node makes itself does not count, so that a fault someone can
cause over the air does not open it.

**Why `WIPE`.** A node that changes hands, or goes off to be mended,
carries its owner's identity, sessions, groups and messages. Erasing it
on the node needs a screen to choose the page; erasing it over USB needs
a computer. The phone already driving the node is the thing the owner
has. Anyone who can send `WIPE` could already read all of it, so it
gives nothing new to someone who pairs. It has no field to confirm it:
over a byte stream a frame has a CRC and a type, and a client is held to
asking its user first. The airtime is kept because a region's limit
does not start again because a board was erased.

**Why a conversation is forgotten on the node, and not only in a
client.** A client could delete its own copy and tell nobody. But a
node may be driven by several clients, a phone and a laptop and its own
screen, and a conversation deleted on one would live on in the others,
and in the node's flash, where whoever holds the node can
[read it](#what-the-node-holds). The node is already where the user's
names and what they have read are kept for every client; what they have
forgotten belongs with them. And it is the node that is lost or taken,
and the node's copy that most needs to go.

**Why a mark, and not a record for each message.** A client that was
away holds messages the node may have long since dropped for room, so
telling it which ones were forgotten would mean a record for each, kept
until every client had seen it, which a node cannot know. A
conversation's messages are already in order of `id`, so one number
says which of them are gone, the client's older copies included, and
`READ` already marks read the same way. A mark only grows, so a sync
can send every one the node holds without a client having to tell the
old from the new, and sending it twice is harmless.

**Why a waiting message is given up.** A message the user forgot that
went on being sent would reach its destination, and its state would
change, when no client holds it any longer to say so. A user who
forgets a conversation means it gone, and `END_SESSION` and
`LEAVE_GROUP` already give up a message in the same way. A client says
so before it asks.

**Why not a flag on `LEAVE_GROUP` and `REMOVE_CONTACT`.** A group left
keeps its messages, and is the conversation a user most often wants
gone afterwards; the same is true of an address that was never a
contact. A request of its own forgets either, at any time, and a client
that offers to forget while it leaves sends both.

**Why only conversations.** A mark cannot say that one message in the
middle is gone, and a record for each would be what the mark avoids. A
conversation is what users clear. One message forgotten can come
later, as its own record, if it is wanted.

**Why hiding is not here.** Hiding a conversation, or archiving it, is
how a client arranges what it shows, and changes nothing the node or
another client holds. Each client may do it as it likes; nothing in it
needs a frame.

## Not yet specified

* **Who is in a group.** A node does not know, and nor does a client:
  it sees the routing ids that have written.
* **Replacing a group's secret** from a client: a request for it, and
  news that a member replaced it. [Groups](groups.md#replacing-the-secret)
  defines what goes on the air; a node follows a replacement whatever
  its client's version, and the group keeps its id.
* **What is left of the airtime budget**: `reason` 4 names
  [the budget](airtime.md), and `AIRTIME` gives only the region's
  limit. Fields for what is left are
  [proposed there](airtime.md#not-yet-specified), not yet added.
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
* **Movement**: a fix's speed and heading, which a receiver gives and
  `FIX` does not carry, as [Positions](positions.md#not-yet-specified)
  does not.
* **How often a receiver runs.** A node runs its receiver all the time
  or not at all; one that woke it now and then would draw less, and
  have an older fix.
* **What became of a position** sent: whether it went, and whether a
  contact acknowledged it.
* **Developer frames**: routes, links and counters for whoever is
  debugging the mesh, which the console shows today.
* **Signatures checked by a bootloader**, so that a node updated by
  its bootloader takes only signed images too. Until then it takes any,
  from anyone in range, while its bootloader waits.
* **Withdrawing a release key** sooner than a release that drops it can
  reach every node.
* **Erasing on the node**, for a node without a screen: a gesture of its
  button that does what `WIPE` does.
* **Bluetooth while a node sleeps.** A sleeping node keeps its
  Bluetooth link, and advertises, as it would awake, though its
  processor could sleep too if it did not. When it may stop
  advertising, and how a client finds it again, is not said.
* **The leaves a relay keeps**: a relay's client sees none of the
  sleeping leaves it holds frames for, nor how many it holds.
* **Turning a node off for a while**: an `OFF` that says when the node
  comes on again by itself.
* **Telling the other clients** that a node is turning off. A node
  may be driven by several, and only the one that sent `OFF` is told:
  the rest see a node gone.
* **Driving another node over the air**, to turn it off or anything
  else: who may, and how a node knows them.
* **Forgetting one message**, rather than a conversation up to a point.
* **Forgetting by age**: a node that forgets what is older than the
  user chose, by itself, and tells its clients as it does.
* **How many cards a sync sends.** A node in a crowd may hold a day of
  cards, and each is a frame of a sync. A node holds what it has room
  for, and nothing yet lets a client ask for fewer.
