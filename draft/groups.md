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
   [unicast message](unicast-security.md) carries, and four more inside
   for who wrote it.
3. **Nothing in clear that names the group or the writer.** An observer
   sees values that look random and change with every frame. It cannot
   tell two groups' frames apart, or two writers'.
4. **No time sync, and no state to agree on.** A member needs the
   secret and nothing else: no counter shared between writers, no
   clock, no list of members.
5. **Standard primitives only**, and the ones a node already has:
   HKDF-SHA-256, AES-128 and AES-128-CCM.

What this does **not** give, and a reader should know before the rest:

* **A member can write as any other.** Every member holds the one key,
  so the group can tell that a member wrote a frame and not which.
* **No forward secrecy.** Whoever comes to hold the secret, by being
  invited or by taking a member's node, can read every frame the group
  ever sent that they recorded.
* **Nobody can be removed.** A member who leaves, or is no longer
  wanted, still holds the secret. The others start a new group.

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
GK = Expand(G, "tern v0 group key", 16)        group key
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
| 15 | 4 + `c` | ciphertext | yes (encrypted) |
| 19 + `c` | 8 | AEAD tag | |

`hdr` is `0x60`: format `01`, draft 0; type `100`, a group frame; flags
`000`, none defined. The frame is `27 + c` bytes, so `c`, the length of
what the writer has to say, is at most 228.

What is encrypted is the **plaintext**:

| Offset | Bytes | Field | |
|---|---|---|---|
| 0 | 4 | `from` | the writer's routing id |
| 4 | `c` | `content` | what the writer has to say |

For a frame with nonce `N`:

```
gtag(N)  = AES(GT, 0^8 || N)[0..4]
A        = hdr || N || gtag(N)
P        = from || content
frame    = hdr || hops || power || N || gtag(N) || CCM(GK, 0^5 || N, A, P)
```

## Sending

1. The writer MUST draw `N`, 8 bytes, at random for each frame, from a
   generator fit for keys. It MUST NOT count, and MUST NOT make `N` from
   anything that names the node or the time.
2. `from` is the writer's own routing id.
3. The frame is as above, and is [flooded](flooding.md#sending).

A frame is sent once. Nothing acknowledges it, and a writer does not
learn who received it.

## Receiving

A member holds, for each group, the nonces of the last `RECENT` frames
it accepted for that group.

To receive a group frame, which the flood hands over once however many
copies arrive:

1. A node MUST discard a frame shorter than 27 bytes.
2. For each group it holds, it computes `gtag(N)` from the frame's
   `nonce` and compares it with the frame's `gtag`. If none matches,
   the frame is not for this node, and it MUST NOT treat that as an
   error. Most frames a node hears are for groups it is not in.
3. For each group that matches, in any order, it checks and decrypts
   the ciphertext with that group's `GK`. Four bytes can match more
   than one group, so a node MUST try every match before deciding that
   a frame fails.
4. A node MUST NOT accept a frame unless the AEAD check passes; unless
   `from` is neither `0x00000000`, `0xFFFFFFFF` nor its own routing id;
   and unless `N` is not among the nonces it holds for that group.
5. On accepting a frame, it adds `N` to the group's nonces, dropping
   the oldest if it then holds more than `RECENT`.

Whether a node passes the frame on is [the flood's](flooding.md#passing-on)
to say, and does not depend on any of this: a relay that holds no group
passes on every group's frames.

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

A node **leaves** a group by erasing `G`, `GK`, `GT` and the nonces.
The others are not told, and their frames still reach it as frames it
cannot open.

## Parameters

| Name | Value | |
|---|---|---|
| `RECENT` | 64 | nonces kept for each group |

## Conformance

An implementation conforms to this section if, for
[`vectors/groups.json`](../vectors/groups.json):

* **accepted:** given `group_secret`, `nonce`, `from`, `content`,
  `hops` and `power` (setting the nonce is a test hook; in use, a
  writer draws it), it produces exactly `frame`, and, as a member
  holding `group_secret` whose routing id is `self`, it accepts `frame`
  and recovers `from` and `content`;
* **rejected:** as a member holding `group_secret` whose routing id is
  `self`, it does not accept `frame`;
* **members:** as a node whose routing id is `self`, holding every
  group in `groups` and no nonces, given each frame of `deliveries` in
  order, it accepts exactly those whose `accept` is true, for the group
  `group`, with that `from` and `content`. These check that a frame for
  a group not held is passed over, that every group whose tag matches
  is tried, and that a frame is accepted once;
* **recent:** as a member holding `group_secret` and no nonces, given
  the frames with nonces `first` to `first + count - 1`, each as eight
  bytes, in order, and then each of `again`, it accepts those whose
  `accept` is true. A nonce more than `RECENT` frames old is forgotten,
  and its frame accepted again: this checks where that edge is;
* **invites:** it builds `plaintext` from `group_secret` and `name`,
  and reads them from it;
* **bad_invites:** it ignores each `plaintext`.

That a nonce is random, and that an invite waits for the user, cannot
be checked by vectors. They are requirements nonetheless, checked by
reviewing an implementation.

Each `accepted` case also gives the intermediate values (the two keys,
the CCM nonce, the tag and the plaintext) to help find where an
implementation goes wrong.

## What an observer learns

An observer who does not hold the secret learns that a frame is a group
frame, and its length. `nonce` is random and `gtag` is a function of it
that only members can compute, so two frames of one group look no more
alike than two frames of different groups, and nothing in either names
a node. [The flood](flooding.md#what-an-observer-learns) says what its
own three bytes give away.

What it can still do is count. Frames that leave one place soon after
each other are likely one conversation, whatever they carry.

A member learns what the frame says: the content, and a routing id the
writer chose to give.

## Rationale

**A shared key, and its price.** The three things this section does not
give each have a known remedy, and each remedy costs what a mesh on
LoRa has least of.

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

**No clock.** A frame carries no time, so a node that does not know the
time can read and write, as for unicast. The cost is under
[Not yet specified](#not-yet-specified): replay.

**Invites over sessions.** A secret typed in, or shown as a code, would
need no session, and the companion link may yet offer both. An invite
over a session needs nothing new on the air but one flag, comes from a
node the user has already chosen to talk to, and is as private as
anything else the two say.

## Not yet specified

* **Replay, past the nonces kept.** A frame recorded and flooded again
  once its nonce has left a member's `RECENT` is accepted again, as a
  new message with old words. A time in the plaintext would close it
  for nodes that know the time.
* **Signed frames**, for groups that will pay for them.
* **A new secret for a group**, handed round by its members without
  each inviting the rest again.
* **What `content` is**: its text, and whether anything says a frame
  answers another. As for a unicast message, this section carries
  bytes.
* **Length.** The ciphertext is as long as the plaintext.
* **Measured cost**: tag checks for each group held, on the nRF52840.
