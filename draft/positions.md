# Positions

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Every number in it
is **provisional**, and nothing in it is measured. A position to a
group needs a flag that [Groups](groups.md) and
[Frames for every node](flooding.md) do not yet define: see
[Not yet specified](#not-yet-specified).

A user may let chosen contacts, or a group, see where they are, so
that a phone app can show them on a map. This section defines what a
**position** is on the air, how coarse a user can make it, which
frames carry it, when a node sends one, and what a node does with one
it receives. A client turns sharing on and off, and gives the node its
position, over the [companion protocol](companion.md#positions).

Test vectors: [`vectors/positions.json`](../vectors/positions.json),
produced by
[`vectors/tools/positions.py`](../vectors/tools/positions.py).

## Goals

1. **Only to whom the user chose.** A position goes encrypted, end to
   end, to a contact over a [session](unicast-security.md) or to a
   [group](groups.md) the node holds, and to no one else. Nothing in
   clear says where a node is. No position goes anywhere until the user
   turns sharing on for that contact or that group.
2. **No more exact than the user chose.** The user picks how coarse a
   position is, for each contact and group. A coarse position is a
   cell of a grid, and the same cell every time, so that many of them
   tell no more than one.
3. **Coarser is smaller.** A position is two bytes, and as many more as
   its precision needs: three for a town, six for a few metres.
4. **Nothing new on the air.** A position is a message for the node, in
   the frames that already carry one. It is sealed, routed, flooded and
   acknowledged as those frames are.
5. **Seldom.** A node sends a position when it has moved, no more often
   than the user chose and never more often than a floor, and refreshes
   one that has not changed once an hour.
6. **Integers, and no clock.** Every field is a whole number, and a
   node needs no time of day to send or read one.

What this does **not** give, and a reader should know before the rest:

* **A recipient keeps what it was sent.** Turning sharing off stops new
  positions, and asks recipients to forget the last; it cannot make
  them.
* **A group member can claim to be another.** As for every
  [group frame](groups.md#goals), the writer of a group's position is
  what the frame claims.
* **An observer can tell that a frame is for the node**, and when such
  frames are sent: see [What an observer learns](#what-an-observer-learns).

## Notation

As in [Secured unicast frames](unicast-security.md#notation). Fields
are big-endian; `u8` is unsigned and `i16` two's complement. A
**destination** is a contact or a group that a node shares its
position with. Latitude and longitude are WGS 84, in degrees, north and
east positive; where a value is given as an integer it is in units of
10⁻⁷ degree, as `lat` and `lon`. `/` between integers is division
rounded down, and `<<` and `>>` are shifts.

## Where a position goes

**To a contact**, in a [secured unicast frame](unicast-security.md#the-frame)
whose `hdr` has the flag `node` set, `0x49`, with the position as its
plaintext. It takes the session's next counter, follows a route, and is
[acknowledged](forwarding.md#messages), as any message is.

**To a group**, in a [group frame](groups.md#the-frame) whose `hdr` is
`0x61`: the group frame's `0x60` with flag bit 0, `node`, set, as a
unicast frame's is. `content` is the position. It is sealed with the
group's keys, [flooded](flooding.md#sending) and charged to the node's
own [allowance](flooding.md#the-allowance) as a group's message is, and
nothing answers it.

In each, the first byte of what is sealed says what it is, as
[for an invite](groups.md#invites): `0x02` is a position. A node MUST
NOT put a position on the air in any other frame.

## The position

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x02`: a position |
| 1 | 1 | `form` | bits 7–3: `precision`, 0 to 24. Bits 2–0: which optional fields follow |
| 2 | `w` | `where` | the cell, below; `w` is 0 if `precision` is 0 |
| | 2 | `altitude` | `i16`, if `form` bit 0 is set |
| | 1 | `accuracy` | `u8`, if `form` bit 1 is set |
| | 1 | `age` | `u8`, if `form` bit 2 is set |

The optional fields that are present follow `where` in this order.

### The grid

A position at `precision` `b`, from 1 to 24, is a **cell**: one of
`2^b` columns of equal width in longitude, from 180° west eastwards,
and one of `2^(b-1)` rows of equal height in latitude, from the south
pole northwards. So a cell is `360 / 2^b` degrees each way. For a point
at `lat` and `lon`, in 10⁻⁷ degree:

```
row     = min(((lat + 900000000) << (b - 1)) / 1800000000,  2^(b-1) - 1)
column  = (((lon + 1800000000) << b) / 3600000000)  mod 2^b
```

The north pole is in the top row, and 180° east is 180° west. Every
value here fits in a signed 64-bit integer. A node MUST compute the
cell this way, from its fix in 10⁻⁷ degree, rounded to the nearest.

`where` is `row`, in `b - 1` bits, then `column`, in `b` bits, most
significant bit first, then zero bits to the end of the last byte: `w`
is `(2b - 1 + 7) / 8` bytes. A receiver takes the cell to cover

```
south  = ((row × 1800000000) >> (b - 1)) - 900000000
west   = ((column × 3600000000) >> b) - 1800000000
```

and northwards and eastwards one cell's size from there, and shows it
at its centre:

```
lat    = (((2 row + 1) × 1800000000) >> b) - 900000000
lon    = (((2 column + 1) × 3600000000) >> (b + 1)) - 1800000000
```

What each precision costs, and how fine it is, for the five that
clients are asked to offer:

| `precision` | `w` | A cell, north to south | Plaintext | Unicast frame | Group frame |
|---|---|---|---|---|---|
| 8 | 2 | 156 km: a region | 4 | 27 | 31 |
| 12 | 3 | 9.8 km: a town | 5 | 28 | 32 |
| 16 | 4 | 610 m: a neighbourhood | 6 | 29 | 33 |
| 20 | 5 | 38 m: a street | 7 | 30 | 34 |
| 24 | 6 | 2.4 m: as exact as there is | 8 | 31 | 35 |

East to west a cell is as wide at the equator, and narrower towards the
poles: half as wide at 60°. A position with all three optional fields
is four bytes longer.

A client that offers a choice of precision SHOULD offer these five, by
what each covers, and MAY offer the others.

### The optional fields

**`altitude`** is the height above the WGS 84 ellipsoid, in metres,
rounded to the nearest. `-32768` is not a value: a sender that does not
know the height leaves the field out.

**`accuracy`** is the sender's estimate of how far the true position
may be from the point it measured, in metres, rounded up: from 1, and
255 for 255 or more. 0 is not a value.

**`age`** is how old the fix was when the position was first sent:

| `age` | |
|---|---|
| 0 to 59 | that many seconds |
| 60 to 254 | `age - 59` whole minutes, rounded down: 1 to 195 |
| 255 | 196 minutes or more |

A position without `age` is as of when it was sent. A sender SHOULD
give `age` for a fix 60 seconds old or more.

### Stopped

A position whose `precision` is 0 is **stopped**: the sender has
stopped sharing its position with the destination, and asks it to
forget the last one. It has no `where`, and `form` is 0: it is the two
bytes `0x02 0x00`.

## Reading a position

A node reads a position from the plaintext of a unicast message, or
the `content` of a group frame, whose flag `node` is set and whose
first byte is `0x02`. It MUST ignore one:

* shorter than its fields, as `form` gives them;
* whose `precision` is more than 24;
* that is stopped, with any of `form`'s bits 2–0 set;
* with a zero bit of `where`'s last byte set to 1;
* with `altitude` `-32768`, or `accuracy` 0.

It MUST read past any bytes after the fields: that is how a later draft
adds one. A message that carried a position it ignores is acknowledged
like any other.

**Who sent it.** A position in a unicast message is from the other
end of the session it came by, which [first contact](first-contact.md)
proved. A node MUST ignore a position in a unicast message from an
address that is not a contact, though it shares a session with it:
whose position a user is shown is theirs to choose, as whom they share
with is. One in a group frame is from the routing id in the frame's
`from`, which is what [a member claimed](groups.md#receiving). A node
that shows a group's position under a name it knows by that routing id
SHOULD NOT show it as proved.

**What a node keeps.** A node holds, for each contact, the last
position it received from it, and for each group, the last from each
routing id. A position replaces the one held from the same sender. A
stopped position replaces nothing: the node MUST forget the position
it holds from that sender. A node MUST forget a position
`POSITION_KEEP` after it received it, every position from a contact or
group it no longer holds, and the position held from a contact when it
is removed.

**Older positions.** Messages over a session can arrive out of order,
and an older position must neither replace a newer one nor bring back
one that was stopped. So for each session a node keeps the counter of
the last message it took a position from, stopped or not, for as long
as it holds the session, and whether or not it still holds the
position. It MUST ignore a position in a message over that session
whose counter is lower. A new session starts with none: the old
session's messages can no longer be opened.

## Sharing

A node shares its position with a destination only while its user has
**turned sharing on** for that destination: for a contact, on the node
itself or by a client's [`SHARE`](companion.md#positions); for a group,
the same, by `SHARE_GROUP`. Sharing is off for every contact and group
until then. A node MUST NOT turn it on for a destination because
another node asked, by default, or by any setting that covers contacts
or groups the user has not chosen one by one.

For each destination, the user chooses:

* **`precision`**, 1 to 24;
* **which optional fields** go with it: altitude, accuracy, or both.
  A node MUST NOT send either unless the user chose it, and gives
  `age` when the rule above says to;
* **`interval`**, the least time between two positions, in seconds:
  at least `POSITION_MIN` for a contact and `POSITION_GROUP_MIN` for a
  group;
* **how long**: until it is turned off, or for a number of minutes,
  after which the node turns it off.

Sharing with a contact ends when the contact is removed, and with a
group when the group is left. When sharing with a destination is
turned off, or ends, after a position has gone to it, a node SHOULD
send it a stopped position, once.

A client that offers altitude or accuracy SHOULD offer them only with
a precision of 20 or more: each says more of a coarse position than its
cell does.

A node learns its own position from a receiver of its own, or from a
client, by [`SET_POSITION`](companion.md#positions). It uses the more
recent fix of the two.

## When a position is sent

For each destination, a node holds when the last position it sent
there first went on the air, `last`, and its cell, from the time
sharing was turned on or last changed; until a position has gone, it
holds neither. At time `now`, with a fix `a` seconds old whose cell, at
the destination's precision, is `cell` (the cell the node takes it to
be in, by the rule on a cell's edge below), a position
is **due** if:

1. `a` is no more than `POSITION_STALE`; and
2. no position has gone since sharing was turned on or last changed;
   or `now - last` is at least `interval`, and either `cell` is not the
   last position's or `now - last` is at least `POSITION_REFRESH`.

A node MUST NOT send a position that is not due, and SHOULD send one
that is, after a random wait, uniform up to an eighth of `interval`.
Only the cell counts: a change of altitude, accuracy or age alone is
not a move.

**A cell's edge.** A user who stands on the line between two cells
would otherwise send each in turn, and say where the line is. So once
a node has sent a cell to a destination, it SHOULD take the fix as
still in that cell until the fix is outside it by more than a quarter
of a cell's height or width.

**One at a time.** A node holds at most one position for each
destination that has not yet gone on the air: a newer one takes its
place. It MUST NOT send a position to a contact while the last it sent
there is neither [acknowledged nor given up](forwarding.md#messages);
the newer waits. A position given up is not sent again: the next one
is sent when due.

**No first contact for a position.** A node MUST NOT begin
[first contact](first-contact.md) to send a position. A position to a
contact it shares no session with is not sent.

**Words first.** A position to a group is paid for from the same
[allowance](flooding.md#the-allowance) as the group's messages, and
must not use up what a message needs. A node MUST NOT send a position
to a group unless the bucket for its own floods, once the position's
airtime is taken from it, would still hold the airtime of a 255-byte
frame. A node with a message and a position ready for the air SHOULD
send the message first.

## Parameters

| Name | Value | |
|---|---|---|
| `POSITION_MIN` | 60 s | the least `interval` for a contact |
| `POSITION_GROUP_MIN` | 300 s | the least `interval` for a group |
| `POSITION_REFRESH` | 3600 s | an unchanged position is sent again after this |
| `POSITION_STALE` | 3600 s | a fix older than this is not sent |
| `POSITION_KEEP` | 24 h | a received position is forgotten after this |

## Conformance

An implementation conforms to this section if, for
[`vectors/positions.json`](../vectors/positions.json):

* **grid:** from `latitude`, `longitude` and `precision` it finds the
  cell `row` and `column`, and writes it as `where`; and from `where`
  it finds the cell, its `south` and `west`, and its centre,
  `centre_latitude` and `centre_longitude`;
* **positions:** from the fields given, it builds `plaintext`, and
  reads from `plaintext` what `read` gives;
* **extended:** it reads `read` from `plaintext`, reading past the
  bytes after the fields;
* **ignored:** it reads no position from `plaintext`;
* **ages:** it writes an age of `seconds` as `byte`, and reads `byte`
  as `read_seconds`;
* **frames:** with the session or group given, it seals `plaintext` or
  `content` as `frame`, and opens `frame` to find it (setting the
  counter and the nonce is a test hook, as in the sections that define
  the frames);
* **receiving:** as a node that shares one session with the sender,
  holding nothing from it, given each delivery in order, as a message
  with `counter` whose plaintext is `plaintext`, from an address that
  is a contact or not as `contact` says, it holds after each the
  position `holds` (`null` for none). This checks that an older
  position is ignored after a newer one, and after a stopped one, and
  that one from an address that is not a contact is ignored;
* **schedule:** for a destination whose `interval` is given, whose last
  position went at `last_at` (`null` for none since sharing began), at
  time `now`, with a fix `age` seconds old whose cell has `changed`
  since that position or not, it finds a position due or not, as `due`
  says.

`sizes` gives the length of each frame, and its time on air by
[Radio settings](phy.md#time-on-air), for the table above; it checks
nothing that `positions` does not.

That nothing is sent until sharing is turned on, the random wait, a
cell's edge, and which fix is the more recent cannot be checked by
vectors. They are checked by reviewing an implementation, and by
running a client against it.

## What an observer learns

An observer who does not hold the session's or the group's keys learns
no position: the cell is encrypted. What it does learn:

* **That a frame is for the node.** The flag `node` is in `hdr`, which
  is in clear, so an observer sees that a unicast or group frame
  carries something other than words. Today that is an invite or a
  position, and an invite is rare.
* **Its length**, which is the precision and the fields chosen, to
  within a byte or two. A position is shorter than most messages.
* **When**, and how often. A node that sends only when it moves sends
  when its user moves, and a node that sends on a schedule sends on a
  schedule. The random wait blurs the second, not the first.
* For a contact, what [every routed frame](forwarding.md#what-an-observer-learns)
  shows: the routing id of the node it is for.

And the transmitter itself is where it is: anyone with a direction
finder can locate a radio that sends, whatever it says.

## Rationale

**A message for the node, not a frame of its own.** Unicast frames
already carry plaintext for the node, marked by a flag and named by its
first byte, for [invites](groups.md#invites). A position in the same
way needs no new frame type, no new rule for relays, and nothing new in
the session: it is sealed, routed, acknowledged and counted as any
message is. A group frame had no such flag, and the smallest change is
the same flag there, in a byte that is already authenticated and in
three bits that are already reserved.

**The flag's cost.** The flag is in clear, so it tells an observer
which frames are not words. A kind inside every plaintext, with no
flag, would hide that: one byte more on every message, and a change to
every receiver. For draft 0 the flag is reused; whether to hide it is
[an open question](#not-yet-specified).

**A grid, not noise.** A position made coarse by adding a random
offset can be made exact again by averaging: a hundred offsets around
one place point at it. A cell of a fixed grid is the same cell however
often it is sent. The grid is the world's, not the sender's, so it is
the same on every node, and a cell of one precision is inside one cell
of every coarser one: a friend who is sent a street, and is in a group
that is sent a town, learns nothing from the town.

**Bits, not decimal places.** Each step of `precision` halves a cell
each way, and each byte of `where` is four steps, so a coarser position
is shorter by a byte for every sixteen-fold step. A count of decimal
places would step by ten and fill bytes unevenly. Columns span 360°
and rows 180° with one bit fewer, so a cell is square in degrees and
the bits that go are always the finest.

**Integers.** A node may have no floating point, and two that round
floating point differently would send different cells for one place.
In 10⁻⁷ degree a coordinate fits a signed 32-bit integer, to about a
centimetre, and the grid is a shift and a division in 64 bits.

**Twenty-four at most.** A cell of 2.4 m is finer than a phone's fix
outdoors. A finer one would be a seventh byte that says nothing true.

**Four bytes more for everything else.** Altitude in whole metres fits
two bytes for any height a person stands at. Accuracy as a byte of
metres is enough for a map to draw a circle round a point, and is
meaningless beside a coarse cell. An age that is fine for the first
minute and coarse after costs one byte; a time of day would cost four,
and would need a clock.

**An age, not a time.** Neither [unicast](unicast-security.md#goals)
nor [groups](groups.md#goals) needs a node to know the time, and
positions keep that. A receiver knows when it received a position;
the age says how much older the fix is. What it does not know is how
long the frame took to arrive, which on a mesh is seconds, and up to a
minute when a frame is sent again.

**Ellipsoid, not sea level.** A receiver of satellite signals measures
height above the WGS 84 ellipsoid, and the difference to sea level
needs a model of the geoid that a node has no room for. A phone
converts for its user.

**When a position is sent.** Positions are what fills a channel if
nothing stops them: no person sends them, they go on a schedule, for as
long as a node is on. So a node sends one only when its cell changes,
which at a coarse precision is seldom, and once an hour to say it is
still there. The floors keep a user from asking for more than the
channel holds. A position to a contact, at `EU868`, is a frame of 25
to 35 bytes and an acknowledgement of 19, 130 to 145 ms on the air for
each hop: one every quarter of an hour while walking is some fourteen
seconds a day. A position to a group is one flood, 75 to 90 ms each
time a relay passes it on; one every five minutes is at most a
sixteenth of the 0.5% of its time a node may
[flood](flooding.md#the-allowance) with, and the rule on the allowance
leaves a message room whatever a group's positions have spent.

**Positions do not make first contact.** First contact is four frames,
one of them 80 bytes, to carry one of about thirty; and a contact that
has not answered may not want to.

**Stopped.** A user who stops sharing expects to vanish from the map.
The node cannot make a recipient forget, but it can ask, in two bytes,
and every conforming node does as asked.

**A cell's edge.** Someone who lives where two cells meet would send
one cell and then the other as they walk about the house, and a
watcher would learn that the line runs through it: more than either
cell says. Holding a cell until the fix is a quarter-cell past it stops
that, at the cost of a position that can be a quarter-cell out.

**`POSITION_KEEP`.** Where someone was a day ago is not what a map of
where people are is for, and a node that is lost or taken should give
up as little as it can.

## Not yet specified

* **The group frame's flag, in [Groups](groups.md) and
  [Frames for every node](flooding.md).** Groups defines no flags, and
  Frames for every node floods only `hdr` `0x60`. Positions to a group
  need both to take `0x61` as above: flag `node`, a first byte that
  names the kind, kinds that a member does not know ignored, and relays
  that pass `0x61` on as they do `0x60`. Until they are amended, a
  relay of today drops every position to a group.
* **Hiding the flag**: a kind in every plaintext, words included, so
  that an observer cannot tell a position from a message. It costs a
  byte on every message.
* **Padding**: positions of one length whatever their precision, so
  that the length does not tell the precision. It costs the bytes that
  goal 3 saves.
* **Cells that keep their width** towards the poles, by fewer columns
  at high latitudes. At 60° a cell is half as wide as it is tall, so a
  user there shares a narrower strip than the table says.
* **Asking for a position**, by a contact, with the user's consent each
  time, in place of or beside sharing on a schedule.
* **Movement**: speed and heading. They would follow the optional
  fields.
* **Places**: a point that is not where a node is, such as a meeting
  point, sent to a contact or group as a message.
* **Order in a group.** Group frames carry no counter, so an older
  position flooded late, after a stopped one, shows the writer where
  they were. A counter or a time in the position would close it, at a
  cost of bytes on every group position.
* **Replay** in a group, as for every [group frame](groups.md#not-yet-specified):
  a position recorded and flooded again once its nonce has been
  forgotten shows the writer where they were.
* **What became of a position**: a client sees when it shares and
  what it receives, not which positions went or arrived.
* **Measured cost**: on radios, and in the simulator with positions in
  its workload.
