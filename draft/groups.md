# Groups

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It has not yet been
reviewed by a cryptographer, and it must be before it is frozen.

A **group** is a set of nodes that share a secret. This section defines
the frame one of them writes for all the others, the keys it is sealed
with, what a member does with one it receives, and how a node is handed
a group's secret. The frame reaches the others as
[a flood](flooding.md).

Test vectors: [`vectors/groups.json`](../vectors/groups.json), produced
by [`vectors/tools/groups.py`](../vectors/tools/groups.py).

## Goals

1. **One frame, however many members.** A message to a group costs the
   airtime of one flood, whether three nodes hold the secret or three
   hundred.
2. **Little overhead.** 23 bytes a frame, what a
   [unicast message](unicast-security.md) carries, and eight more
   inside: who wrote it, and which of its frames this is.
3. **Nothing in clear that names the group or the writer.** An observer
   sees values that look random and change with every frame. It cannot
   tell two groups' frames apart, or two writers'.
4. **No time sync, and no state to agree on.** A member needs the
   secret and nothing else: no counter shared between writers, no
   clock, no list of members. A writer counts its own frames, and asks
   nobody.
5. **A frame is read once**, by a member that still holds its writer.
   A frame recorded and sent again is not read again by a member that
   read it, nor by one that has since read later frames from the same
   writer, for as long as the member [holds that writer](#receiving):
   until it forgets it for another, or restarts without keeping it.
6. **Standard primitives only**, and the ones a node already has:
   HKDF-SHA-256, AES-128 and AES-128-CCM.

What this does **not** give, and a reader should know before the rest:

* **A member can write as any other.** Every member holds the one key,
  so the group can tell that a member wrote a frame and not which.
* **No forward secrecy.** Whoever comes to hold the secret, by being
  invited or by taking a member's node, can read every frame the group
  ever sent that they recorded.
* **Nobody can be removed.** A member who leaves, or is no longer
  wanted, still holds the secret. The others start a new group.
* **A member can silence another.** A frame that claims another's
  routing id and a high `count` makes the members that accept it refuse
  that writer's own frames from then on. It follows from the first.

[Rationale](#rationale) says why, and what each would cost.

## Notation

As in [Secured unicast frames](unicast-security.md#notation): `||`,
`x[a..b]`, `0^k`, `Expand(K, info, L)`, `AES(K, x)` and
`CCM(K, N, A, P)`, the last with an 8-byte tag and a 13-byte nonce.
`rid(A)` is the [routing id](routing.md#routing-ids) of the address
`A`.

## Keys

A group is defined by its **group secret** `G`, 16 bytes. Whoever makes
a group MUST draw `G` at random, from a generator fit for keys. From
it:

```
GK = Expand(G, "tern v0 group frame", 16)      group key
GT = Expand(G, "tern v0 group tag", 16)        tag key
```

Every member holds the same two keys, for as long as it holds the
group.

## The frame

| Offset | Bytes | Field | Authenticated |
|---|---|---|---|
| 0 | 1 | `hdr` | yes |
| 1 | 2 | `hops`, `power`: for the [flood](flooding.md#the-head) | no |
| 3 | 8 | `nonce` | yes |
| 11 | 4 | `gtag`: the group tag | yes |
| 15 | 8 + `c` | ciphertext | yes (encrypted) |
| 23 + `c` | 8 | AEAD tag | |

`hdr` is laid out as a [unicast frame's](unicast-security.md#the-frame)
is:

| Bits | Field | Value in this section |
|---|---|---|
| 7–6 | format | `01`: draft 0 |
| 5–3 | type | `100`: a group frame |
| 2–0 | flags | bit 0 is `node`; bits 2 and 1 are `0` |

So `hdr` is `0x60`, or `0x61` with `node` set. Other flags are
reserved. The frame is `31 + c` bytes, so `c`, the length of what the
writer has to say, is at most 224.

What is encrypted is the **plaintext**:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 4 | `from` | the writer's routing id |
| 4 | 4 | `count` | which of the writer's frames this is, most significant byte first |
| 8 | `c` | `content` | what the writer has to say |

**`node`** says who `content` is for, as it does in a unicast frame.
Clear, it is for the members' users: words to show. Set, it is for the
node itself, and its first byte says what it is, from the same numbers
as a unicast message for the node: `0x02` is
[a position](positions.md#the-position). A kind goes in a group frame
only where the section that defines it says so, and an
[invite](#invites) does not.

For a frame with nonce `N`:

```
gtag(N)  = AES(GT, 0^8 || N)[0..4]
A        = hdr || N || gtag(N)
P        = from || count || content
frame    = hdr || hops || power || N || gtag(N) || CCM(GK, 0^5 || N, A, P)
```

## Sending

1. The writer MUST draw `N`, 8 bytes, at random for each frame, from a
   generator fit for keys. It MUST NOT count, and MUST NOT make `N` from
   anything that names the node or the time.
2. `from` is the writer's own routing id.
3. `count` MUST be greater than the `count` of every frame the writer
   has sent to that group under that routing id, whatever became of
   the frame, and whether or not the node has restarted or left the
   group and taken it again since. It need not be one greater, and the
   first may be any value. A writer that has sent `2^32 - 1` sends no
   more to that group under that routing id.
4. The frame is as above, and is [flooded](flooding.md#sending).

A frame is sent once. Nothing acknowledges it, and a writer does not
learn who received it.

A node meets rule 3 most simply with one count for every group it
writes to, kept for as long as it keeps its address; a member then
learns from `count` at most how many frames the writer sent to its
other groups in between. A node that counts for each group apart tells them nothing,
and has to keep a group's count after it leaves the group, or begin the
next group it takes above every count it has used.

## Receiving

A member holds, for each group, up to `WRITERS` **writers**. For each,
it holds the routing id, the highest `count` it has accepted from it,
`H`, and which of the counts from `H - (WINDOW - 1)` to `H` it has
accepted.

To receive a group frame, which the flood hands over once however many
copies arrive:

1. A node MUST discard a frame shorter than 31 bytes, or whose `hdr`
   is neither `0x60` nor `0x61`.
2. For each group it holds, it computes `gtag(N)` from the frame's
   `nonce` and compares it with the frame's `gtag`. If none matches,
   the frame is not for this node, and it MUST NOT treat that as an
   error. Most frames a node hears are for groups it is not in.
3. For each group that matches, in any order, it checks and decrypts
   the ciphertext with that group's `GK`. Four bytes can match more
   than one group, so a node MUST try every match before deciding that
   a frame fails.
4. A node MUST NOT accept a frame unless the AEAD check passes, and
   unless `from` is neither `0x00000000`, `0xFFFFFFFF` nor its own
   routing id.
5. If it holds `from` as a writer of that group, it MUST NOT accept a
   frame whose `count` is `H - WINDOW` or less, nor one whose `count`
   it has already accepted. It accepts any `count` above `H`, however
   far, and then `H` is that `count`.
6. If it does not hold `from` as a writer of that group, it accepts the
   frame whatever its `count`, and holds `from` as a writer, with that
   `count` as `H` and no other accepted. If it then holds more than
   `WRITERS` for the group, it forgets the one it last accepted a frame
   from longest ago.

A member SHOULD keep its writers when it restarts. One that does not
accepts again, after a restart, frames it accepted before it.

Whether a node passes the frame on is [the flood's](flooding.md#passing-on)
to say, and does not depend on any of this: a relay that holds no group
passes on every group's frames.

A frame with `node` set is in every other way a frame like any other:
it is sealed, tagged, opened and accepted the same way, and takes its
`count` from the same one as the writer's others. A member that accepts
one whose
`content` is empty, or whose first byte is a kind it does not know or
one that does not go in a group frame, MUST do nothing more with it,
and MUST NOT show it as words.

`from` is what the frame says. A member that shows it to a user as a
name it knows by that routing id is showing what a member claimed.

## Invites

A node is handed a group by a member, in a
[unicast message](unicast-security.md) between two nodes that share a
session. The message's `hdr` has the flag
[`node`](unicast-security.md#the-frame) set, so its plaintext is for
the node and not shown as words, and begins with what it is:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 1 | `kind` | `0x01`: an invite |
| 1 | 16 | `G` | the group secret |
| 17 | 0 to 31 | `name` | what the inviter calls the group, UTF-8 |

* A node MUST ignore an invite shorter than 17 bytes or longer than 48,
  or whose `name` is not valid UTF-8. The message that carried it is
  acknowledged like any other.
* A node MUST NOT take a group from an invite on its own. It tells its
  user who invited it and to what, and holds the group only if the user
  says so.
* `name` is a suggestion. A node MUST NOT send a group's name on the
  air but in an invite.

Any member may invite. A group has no owner.

A node **leaves** a group by erasing `G`, `GK`, `GT` and the writers.
The others are not told, and their frames still reach it as frames it
cannot open.

## Parameters

| Name | Value | |
|---|---|---|
| `WRITERS` | 16 | writers held for each group |
| `WINDOW` | 32 | counts, from the highest accepted down, that may still be accepted |

## Conformance

An implementation conforms to this section if, for
[`vectors/groups.json`](../vectors/groups.json):

* **accepted:** given `hdr`, `group_secret`, `nonce`, `from`, `count`,
  `content`, `hops` and `power` (setting the nonce is a test hook; in
  use, a writer draws it), it produces exactly `frame`, and, as a member
  holding `group_secret` and no writers, whose routing id is `self`, it
  accepts `frame` and recovers `from`, `count` and `content`, and
  whether `node` is set;
* **rejected:** as a member holding `group_secret` and no writers,
  whose routing id is `self`, it does not accept `frame`;
* **members:** as a node whose routing id is `self`, holding every
  group in `groups` and no writers, given each frame of `deliveries` in
  order, it accepts exactly those whose `accept` is true, for the group
  `group`, with that `from` and `content`. These check that a frame for
  a group not held is passed over, that every group whose tag matches
  is tried, that a frame is accepted once, that a writer's counts in
  one group do not stand against its frames in another, and that a
  frame for the node and one of words draw on one count;
* **counts:** as a member holding `group_secret` and no writers, whose
  routing id is `self`, given the frames of `deliveries` in order, each
  of which is `content` from `from` with that `count`, sealed under
  `group_secret` with a nonce of its place in the list, from 0, as
  eight bytes, it accepts exactly those whose `accept` is true. These
  check both edges of the window, that a count is accepted once
  whatever the nonce, that a writer may skip, and which writer is
  forgotten when there are more than `WRITERS`;
* **invites:** it builds `plaintext` from `group_secret` and `name`,
  and reads them from it;
* **bad_invites:** it ignores each `plaintext`.

That a nonce is random, that a writer's `count` never goes back, and
that an invite waits for the user, cannot be checked by vectors. They
are requirements nonetheless, checked by reviewing an implementation.

Each `accepted` case also gives the intermediate values (the two keys,
the CCM nonce, the tag and the plaintext) to help find where an
implementation goes wrong.

## What an observer learns

An observer who does not hold the secret learns that a frame is a group
frame, and its length. `nonce` is random and `gtag` is a function of it
that only members can compute, so two frames of one group look no more
alike than two frames of different groups, and nothing in either names
a node. [The flood](flooding.md#what-an-observer-learns) says what its
own three bytes give away. `hdr` is in clear, so the flag `node` tells
an observer which group frames are not words: today, that they are
[positions](positions.md#what-an-observer-learns).

What it can still do is count. Frames that leave one place soon after
each other are likely one conversation, whatever they carry.

A member learns what the frame says: the content, a routing id the
writer chose to give, and `count`. Two counts from one writer tell it
at most how many frames the writer sent between them that it did not
receive, and, if the writer keeps one count for all its groups, at most
how many of those went to groups it is not in. It is the number itself
only if the writer never skips, and one that restarts does.

## Rationale

**A shared key, and its price.** The first three things this section
does not give each have a known remedy, and each remedy costs what a
mesh on LoRa has least of.

* *Signing each frame* would stop a member writing as another. An
  Ed25519 signature is 64 bytes: more than the whole of a short
  message's frame, on every frame, for every relay that passes it on.
  A flag in `hdr` is free for it.
* *A key for each writer*, handed to every member over sessions and
  moved forward as it is used, gives forward secrecy and lets a group
  drop a member by handing new keys to the rest. It costs a unicast
  message to every member for every writer, again whenever anyone
  leaves, and a key and a counter for every writer in every group on
  nodes that hold sixteen sessions.
* *No group frame at all*, with each message sent to every member in
  turn over sessions, gives everything a session does. It costs a
  message's whole path once a member, which is workable for three and
  not for thirty.

A group here is for a conversation among people who are content to
trust each other with it. Two nodes that want more have a
[session](unicast-security.md).

**A random nonce, not a counter.** Every writer seals under the one
key, and CCM must never see a nonce twice under a key. Writers cannot
share a counter without talking to each other first. A counter for each
writer, with the writer's id beside it, would never repeat, and would
put a name and a count on every frame, which is what goal 3 rules out.
Sixty-four random bits repeat by chance: among `q` frames with
probability about `q^2 / 2^65`, which is one in 37 million for a
million frames: most of a year of one node writing 40 bytes at a time
without pause, at [the flood's allowance](flooding.md#the-allowance).
Two frames that
did share a nonce would give an observer the XOR of their plaintexts,
and not the key.

**A tag from the nonce.** A member could find its frames by trying to
open every one. The tag costs four bytes and saves all but one AES
block for each group held: a node in eight groups does eight block
encryptions for a frame that is not its own, and no CCM. Being a
function of the nonce, it changes with every frame, as a
[destination tag](unicast-security.md#rationale) does.

**The writer inside, as a routing id.** An address is 32 bytes. A
routing id is four, is what a member already knows its contacts by, and
proves as much as an address would here, which is nothing.

**A count, inside.** A frame recorded off the air can be flooded again
by anyone, with no key, and a member has to know it has read it. A
member that keeps the nonces it has accepted knows only for as many
frames as it keeps: that was this section as first drafted, with 64,
and the sixty-fifth frame back read as new words. A count that only
rises needs four bytes for each writer a member has heard, and covers
every frame that writer ever sent. It is sealed, as `from` is, so an
observer sees neither, and it is not the nonce: that stays random. The
price is four bytes on every frame.

**A window of 32.** Two frames one node wrote can arrive in either
order, since each finds its own way through the flood. A member that
took only a `count` above the last would drop the one that was passed.
Thirty-two is what [a session's receiver](unicast-security.md#receiving)
allows behind its highest, and is a bit for each in one word. There is
no limit ahead: a writer may skip, as one does that restarts from a
count it saved some frames before.

**Sixteen writers.** A member cannot keep a count for every routing
id: `from` is a claim, and a member could make any number of them. The
group this section is for is a few people. In one where more than
`WRITERS` write, the writer forgotten is the one unheard longest, and
its old frames can be read again until it writes.

**A new label for the key.** As first drafted, the plaintext had no
`count`, and the group key was `Expand(G, "tern v0 group key", 16)`. A
member of this draft that opened a frame of that one would take four
bytes of its words as a `count`, most likely a high one, and refuse the
writer from then on. With the label changed, neither opens the other's
frames. `GT` is as it was, so each sees the other's as a frame of the
group that fails its check.

**No clock.** A frame carries no time, so a node that does not know the
time can read and write, as for unicast. A time in the plaintext would
do what `count` does only for members that know the time, and would
drop a writer whose clock is wrong without telling it. What `count`
leaves open is under [Not yet specified](#not-yet-specified).

**A flag for the node, as unicast has.** Positions to a group needed
a way to say that `content` is not words. The flag is the one a unicast
frame already has, in a byte that is already authenticated, in bits
that were reserved, and so a frame for the node costs no byte more than
one of words. A kind inside every `content`, words included, would hide
which frames are not words, for a byte on every frame: see
[Positions](positions.md#not-yet-specified). A member of before the
flag drops a frame with it set, as [the flood](flooding.md#the-head)
of before did, and misses positions and no words.

**Invites over sessions.** A secret typed in, or shown as a code, would
need no session, and the companion link may yet offer both. An invite
over a session needs nothing new on the air but one flag, comes from a
node the user has already chosen to talk to, and is as private as
anything else the two say.

## Not yet specified

* **An old frame a member never read.** A frame recorded and flooded
  again is accepted, as new words, by a member that did not receive it
  and has accepted nothing later from its writer: one that was out of
  reach, one that joined since, or one that has forgotten the writer.
  A time in the plaintext would close it for nodes that know the time.
* **Signed frames**, for groups that will pay for them.
* **A new secret for a group**, handed round by its members without
  each inviting the rest again.
* **What `content` is**, with `node` clear: its text, and whether
  anything says a frame answers another. As for a unicast message, this section carries
  bytes.
* **Length.** The ciphertext is as long as the plaintext.
* **Measured cost**: tag checks for each group held, on the nRF52840.
