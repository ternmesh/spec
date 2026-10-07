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
| `i8` | 1 | two's complement |
| `addr` | 32 | an [address](first-contact.md#addresses) |
| `str` | 1 + `n` | a `u8` length `n`, then `n` bytes of UTF-8; each field gives its longest `n` |

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

Any request may instead be answered by `ERROR`.

### Answers

| `type` | Answer | Fields |
|---|---|---|
| `0x40` | `OK` | |
| `0x41` | `ERROR` | `code` `u8` |
| `0x42` | `INFO` | `version` `u8`, `firmware` `str` up to 31 |
| `0x43` | `SYNCED` | |
| `0x44` | `QUEUED` | `id` `u32` |

`firmware` names the node's software, for a person to read. A client
MUST NOT decide what the node supports from it: that is what `version`
is for.

Error codes:

| `code` | |
|---|---|
| 1 | a request, or a setting, this node's version does not define |
| 2 | malformed |
| 3 | a value the node refuses: a region it does not have, a power it cannot send at, empty text |
| 4 | not a [valid](first-contact.md#addresses) address, or the node's own |
| 5 | no room: the node cannot hold another contact or message |
| 6 | `HELLO` first |
| 7 | the Bluetooth link's MTU is too small ([below](#bluetooth-le)) |
| 8 | not now: the node cannot act on this request until it has finished something else |

Other codes are reserved. A client MUST treat one it does not know as
a refusal.

### News

| `type` | News | Fields |
|---|---|---|
| `0x80` | `SELF` | `address` `addr`, `role` `u8`, `region` `str` up to 15, `power` `i8`, `time` `u32` |
| `0x81` | `CONTACT` | `address` `addr`, `session` `u8`, `name` `str` up to 31 |
| `0x82` | `CONTACT_GONE` | `address` `addr` |
| `0x83` | `MESSAGE` | `id` `u32`, `contact` `addr`, `time` `u32`, `flags` `u8`, `state` `u8`, `reason` `u8`, `wait` `u16`, `text` `str` up to 128 |
| `0x84` | `STATE` | `id` `u32`, `state` `u8`, `reason` `u8`, `wait` `u16` |
| `0x85` | `NEIGHBOUR` | `routing_id` `u32`, `role` `u8`, `snr` `i8`, `heard` `u16` |
| `0x86` | `NEIGHBOUR_GONE` | `routing_id` `u32` |
| `0x87` | `AIRTIME` | `period` `u32`, `allowed` `u32`, `used` `u32`, `wait` `u32` |
| `0x88` | `POWER` | `millivolts` `u16`, `percent` `u8`, `flags` `u8` |

Each news frame but `STATE` and the two `_GONE`s is a **record**: the whole of one
thing as the node holds it now. A record replaces any the client holds
for the same thing. `STATE` replaces those fields of the `MESSAGE` with
its `id`.

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
is its clock.

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

### When news is sent

A node with a client that has said `HELLO` MUST send that client:

* `MESSAGE` when a message is sent or received, and when a received
  message is marked read;
* `STATE` when a message's `state` or `reason` changes;
* `CONTACT` and `CONTACT_GONE` when a contact is saved, renamed,
  removed, or gains or loses a session;
* `SELF` when anything in it but `time` changes;
* `NEIGHBOUR_GONE` when the node forgets a neighbour.

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
version 0. Later versions only add types, settings, error codes and
fields at the end of a frame, so any two versions can talk. A change
that cannot be made that way is a new protocol, with its own magic and
its own Bluetooth service.

A client then, typically, sets the node's clock and syncs:

```
client                         node
HELLO       seq 1, version 0  ─▶
                              ◀─  INFO        seq 1, version 0
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
`CONTACT` for every contact, a `MESSAGE` for every message it holds
whose `id` is greater than `after`, a `NEIGHBOUR` for every neighbour,
one `AIRTIME` and one `POWER`. Then it answers `SYNCED`. News that a
change prompts while it syncs is sent as at any other time, among the
rest.

For contacts and neighbours, a sync is the whole list: a client that
receives `SYNCED` MUST forget every contact and neighbour it holds that
the sync did not send, as if it had received its `_GONE`. Messages are
not: a sync sends only those after `after`, and a client keeps the
rest.

A client that holds messages already gives the greatest `id` it holds
as `after`. One that has [missed news](#news) gives one less than the
least `id` of any message it holds that is still waiting or sent,
since those are the ones whose state may have changed unseen. `after`
of 0 asks for every message.

A node keeps only so many messages, and MAY forget the oldest without
news. A client that wants them keeps its own copy.

### Requests, one at a time

A client MUST NOT send a request while one it sent is unanswered: a
node needs room for only one. A client that has had no answer within
`ANSWER_WAIT` gives up on it; for `SYNC`, the wait starts again with
each news frame. An answer whose `seq` is not that of the request the
client is waiting on is one it gave up on, and the client MUST ignore
it.

A request given up on may have been acted on. Every request but `SEND`
can be sent again without harm. `SEND` carries `ref`, the client's own
number for the message, which it SHOULD choose at random for each new
message: several clients may drive one node, and a client may restart,
so a counter would repeat another's. A node that receives a `SEND`
whose `ref`, `to` and `text` are all those of one of the last `REFS`
messages it accepted MUST NOT send another message, and answers
`QUEUED` with the `id` it gave the first. So a client that sends again
with the same `ref` sends one message, whatever became of the first
try, and two different messages are never taken for one.

### Going quiet

A client sends a request at least every `IDLE` seconds, `PING` if it
has nothing else to ask, whether or not news is arriving. If one is
unanswered after `ANSWER_WAIT`, the node has gone, and the client
SHOULD close the connection and open it again.

A node learns that a Bluetooth or TCP client has gone when the
connection closes. Over USB serial it cannot: the port stays open on
the node's side whatever the computer does, and the next program to
open it may be a terminal. So a node on a serial port that has
received no request for `LAPSE` seconds MUST treat the connection as
ended: it stops sending news, and answers any request but `HELLO` with
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

A node MUST refuse, with `ERROR` 3, a region it does not have and a
power its radio cannot send at or that would let it radiate more than
its profile allows. A node MAY restart to apply a setting, after it
has answered: the connection then drops, and the client starts again.

**`SEND`** sends `text` to the node at `to`, as a new message. The
answer, `QUEUED`, means the node has the message and has given it the
`id` in the answer. It says nothing about the air: that is what the
message's state is for. A node MUST refuse an invalid `to`, or its own
address, with `ERROR` 4, and empty `text` with `ERROR` 3. It sends to
an address whether or not it is a contact, making first contact if it
has no session.

**`READ`** marks every received message whose `id` is `through` or
less as read. It is how a client tells the node, and every other
client, that the user has seen them.

**`SAVE_CONTACT`** saves `address` as a contact with `name`, or
renames it if it is one already. An empty name is a name. A node MUST
refuse an invalid address, or its own, with `ERROR` 4.

**`REMOVE_CONTACT`** removes the contact. It removes the name, and
nothing else: messages to and from the address are kept, and so is any
session with it. A node answers `OK` for an address that is not a
contact.

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
* **streams:** given the bytes of `stream` as they arrive, it finds
  the frames and the runs of text in `items`, in that order, and holds
  `pending` waiting for more;
* **exchange:** as a node holding what the exchange shows, given the
  client's frames in order, it sends the node's, in order. This checks
  that an answer carries its request's `seq`, and that news is counted
  from 0 after `HELLO`, through a sync and after it.

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

**Why the node keeps the names.** The node's own screen shows who a
message is from, and a user may drive one node from a phone and a
laptop. A name kept on one client is missing on the node and on the
other. Kept on the node, it is in one place, and still never on the
air, which is what "local" in the firmware's interface draft has to
mean: kept by the user's own equipment.

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
pings, so one lost to a busy port does not end a connection.

**Why the passkey, and not "just works" pairing.** A node may relay
for its neighbours on a hill, and anyone who can drive it can read its
messages and change its region. Passkey entry stops someone in range
from pairing unseen. A node with no screen has no way to show one, so
its passkey is set over USB, which needs the node in hand.

**Why nothing derived from the address in advertisements.** The radio
protocol keeps a node's address out of the clear. A Bluetooth
advertisement that carried it would tell anyone in range which mesh
node they were near, and follow it about.

## Not yet specified

* **Broadcast and groups**, and their messages: the radio protocol has
  none yet.
* **The airtime budget**: `reason` 4 names it, and `AIRTIME` gives only
  the region's limit. The budget's fields come with its section.
* **What a message carries on the air**: its text, its time, whether it
  is UTF-8. This section's `text` is what the user wrote, and the limit
  of 128 bytes is provisional until that is said.
* **A short code to compare addresses**, which the firmware's interface
  draft asks for, the same in every implementation.
* **Whether a node takes first contact from an address that is not a
  contact**, and how a client is asked.
* **Authentication over TCP.** The framing above serves TCP, but
  nothing yet says who may drive a node over a network. Until something
  does, a node SHOULD NOT offer this protocol on a network socket.
* **Developer frames**: routes, links and counters for whoever is
  debugging the mesh, which the console shows today.
* **Firmware updates** over this link.
* **Sleeping leaves**: what a client sees of a node that is off the
  air most of the time.
