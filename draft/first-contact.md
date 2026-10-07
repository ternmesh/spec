# First contact

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). It has not yet been
reviewed by a cryptographer, and it must be before it is frozen: it uses
one key for both signing and key agreement (see
[Rationale](#rationale)).

This section defines what a node's address is, and how two nodes that
share nothing but one's address come to share a session: the handshake
that produces the session secret `S` which
[secured unicast frames](unicast-security.md) start from.

Test vectors: [`vectors/first-contact.json`](../vectors/first-contact.json),
produced by [`vectors/tools/first_contact.py`](../vectors/tools/first_contact.py).

## Goals

1. **Every message in one frame.** The handshake is four frames of 45,
   53, 73 and 17 bytes, so none needs fragmenting. Where a region limits
   each transmission's time, they need a faster setting than its
   slowest ([analysis/first-contact-fit.md](../analysis/first-contact-fit.md)).
2. **No address in clear.** The responder's address is never sent. The
   initiator's is encrypted. An observer cannot tell whom a first
   contact is for unless it holds the responder's private key.
3. **A standard handshake, unchanged.** EDHOC (RFC 9528) with method 3
   and cipher suite 0, the AEAD and hash that unicast frames already
   use. The generator reproduces RFC 9529's published EDHOC traces
   before it computes anything.
4. **Forward secrecy and mutual authentication.** Each side contributes
   an ephemeral key, so capturing a node later does not expose past
   sessions, and each side proves it holds the private key behind its
   address.
5. **One key per node.** A node's address is its Ed25519 public key.
   The same key pair gives it the X25519 key it uses here, and can sign
   what later sections need signed.

## Notation

As in [unicast-security.md](unicast-security.md#notation), and:

* `p` is `2^255 - 19`.
* `Extract(salt, IKM)` is HKDF-Extract from RFC 5869 with SHA-256.
* `X25519(k, u)` is the function of RFC 7748, section 5.
* `EDHOC_Exporter`, `G_X`, `G_Y`, `G_RX`, `C_I`, `C_R`, `ID_CRED_I`,
  `ID_CRED_R`, `CRED_I`, `CRED_R`, `PLAINTEXT_2`, `PLAINTEXT_3` and
  `message_1` to `message_4` are as in RFC 9528.
* `h'..'` is a byte string in hex.

## Addresses

Each node has an **identity key**: an Ed25519 key pair (RFC 8032), made
from a 32-byte seed `sk`. Its public key `A`, 32 bytes, is the node's
**address**.

An address is **valid** if it decodes to a point as RFC 8032, section
5.1.3 requires, and that point is not of small order, that is, `[8]A` is
not the neutral element. A node MUST NOT start a handshake with an
invalid address, and MUST reject a `message_3` that names one.

From its identity key, each node has an **X25519 key**:

```
k     = SHA-512(sk)[0..32]               X25519 private key
U(A)  = (1 + y) / (1 - y)  mod p         X25519 public key
```

`y` is the y-coordinate of the point `A` decodes to, and `U(A)` is
encoded as 32 bytes, least significant first, as RFC 7748 encodes `u`.
`k` is the same 32 bytes that Ed25519 makes its secret scalar from, and
X25519 applies the same clamping to it, so `X25519(k, 9) = U(A)`. A node
computes another node's X25519 public key from that node's address.

## The EDHOC profile

First contact is an EDHOC session, as RFC 9528 specifies it, with these
choices:

| | |
|---|---|
| Method | 3: both ends authenticate with a static Diffie-Hellman key |
| Cipher suite | 0 only, and `SUITES_I` is the integer 0 |
| Static Diffie-Hellman keys | each node's X25519 key, from its address |
| `CRED_x` | `h'a108a101a301012006215820' \|\| A`, the 44-byte CBOR encoding of `{8: {1: {1: 1, -1: 6, -2: A}}}`: a CWT Claims Set whose confirmation claim holds the address as an Ed25519 COSE_Key |
| `ID_CRED_I` | `{14: CRED_I}`, the credential by value (`kccs`, RFC 9528 section 10.6), 46 bytes |
| `ID_CRED_R` | `{4: h'00'}`, a `kid` that the initiator does not need to resolve, sent in its compact form, the one byte `0x00` |
| `C_I`, `C_R` | one byte each, from `0x00` to `0x17` or `0x20` to `0x37`, so each is sent as one byte |
| EAD | none, in any message |
| `message_4` | always sent |
| Error messages | never sent |
| `S` | `EDHOC_Exporter(32768, h'', 32)` |

The initiator of the EDHOC session is the initiator of the unicast
session (`d` = `0x01`), and the responder is its responder.

The messages are then always these lengths, which a receiver checks:

| Message | Bytes | Contents |
|---|---|---|
| `message_1` | 37 | `h'03' \|\| h'00' \|\| h'5820' \|\| G_X \|\| C_I` |
| `message_2` | 45 | `h'582b' \|\| G_Y \|\| CIPHERTEXT_2`, where `PLAINTEXT_2` is `C_R \|\| h'00' \|\| h'48' \|\| MAC_2` |
| `message_3` | 65 | `h'583f' \|\| CIPHERTEXT_3`, where `PLAINTEXT_3` is `h'a10e' \|\| CRED_I \|\| h'48' \|\| MAC_3` |
| `message_4` | 9 | `h'48' \|\| CIPHERTEXT_4` |

Each X25519 computation in the handshake, the ones RFC 9528 makes and
the one below, MUST be checked for an all-zero result, and the handshake
aborted if it is one (RFC 7748, section 6.1; RFC 9528, section 9.2).

## The frame

| Offset | Bytes | Field |
|---|---|---|
| 0 | 1 | `hdr` |
| 1 | 1 | `hop`: for the routing layer |
| 2 | 2 | `label`: for the routing layer |
| 4 | 4 | `ctag_n`: the contact tag |
| 8 | 37, 45, 65 or 9 | `message_n` |

`hdr` has format `01` (draft 0), type `010` (first contact), and as its
flags the message number `n`, from 1 to 4. So it is `0x51`, `0x52`,
`0x53` or `0x54`.

The **contact tags** let the two ends recognise their frames without
naming each other. Both ends can compute `G_RX`, the Diffie-Hellman
result of the initiator's ephemeral key and the responder's X25519 key:
the initiator as `X25519(x, U(A_R))`, and the responder as
`X25519(k_R, G_X)`. Nobody else can. From it:

```
PRK_c   = Extract(G_X, G_RX)
ctag_n  = Expand(PRK_c, "tern v0 contact" || n, 4)
```

`n` is one byte. `hop` and `label` are not protected, as in a unicast
frame.

## Initiating

To contact the node with address `A_R`:

1. The initiator MUST check that `A_R` is valid.
2. It makes a fresh ephemeral X25519 key pair (`x`, `G_X`), chooses
   `C_I`, computes `G_RX` and the contact tags, and sends `message_1` in
   a frame with `ctag_1`.
3. On a frame with `hdr` `0x52` and `ctag_2`, it processes `message_2`
   as RFC 9528, section 5.3.3 requires, with
   `CRED_R = h'a108a101a301012006215820' || A_R`. It MUST reject a
   `PLAINTEXT_2` other than the form above. It then sends `message_3`
   in a frame with `ctag_3`.
4. On a frame with `hdr` `0x54` and `ctag_4`, it processes `message_4`,
   and on success derives `S`.

The initiator MUST NOT send a unicast frame in the session before it
has verified `message_4`.

## Responding

1. On a frame with `hdr` `0x51`, a node checks that `message_1` has the
   form above. If it does, the node computes `G_RX` and `ctag_1`. If
   `ctag_1` is not bytes 4 to 7 of the frame, the frame is not for this
   node, and the node MUST NOT reply to it or treat it as an error.
2. If it is, the node makes a fresh ephemeral key pair (`y`, `G_Y`),
   chooses `C_R`, and sends `message_2` in a frame with `ctag_2`.
3. On a frame with `hdr` `0x53` and `ctag_3`, it processes `message_3`
   as RFC 9528, section 5.4.3 requires. It MUST reject a `PLAINTEXT_3`
   other than the form above, and one whose `CRED_I` holds an invalid
   address. The address in `CRED_I` is the initiator's.
4. On success it sends `message_4` in a frame with `ctag_4`, and
   derives `S`.

Whether a node accepts contact from a given address is up to it. This
section only establishes who the address is.

## Failures and repeats

* A node MUST NOT send an EDHOC error message.
* A frame whose contact tag matches no handshake the node is in, and a
  `0x51` frame whose `ctag_1` does not match, are not for the node. It
  discards them, and they do not affect any handshake.
* A frame whose contact tag matches, but which fails any check in this
  section or in RFC 9528, is discarded, and the node MUST abort that
  handshake and erase its state.
* A node MUST NOT process the same message twice in one handshake. On
  receiving again a frame it has already processed, it MAY send again,
  unchanged, the frame it sent in reply. It MUST NOT compute that reply
  again (RFC 9528, section 7).

## Erasure

Once a node has derived `S`, it MUST erase its ephemeral private key,
every Diffie-Hellman result, and every EDHOC key and pseudorandom key of
the handshake, keeping only what it needs to resend its last frame. It
then treats `S` as [unicast-security.md](unicast-security.md#keys)
requires. A node that aborts a handshake erases the same.

## Conformance

An implementation conforms to this section if, for every case in
[`vectors/first-contact.json`](../vectors/first-contact.json):

* **addresses:** given `seed`, it derives `address`, `x25519_private`
  and `x25519_public`;
* **rejected addresses:** it refuses each `address`, both as an address
  to contact and as the address in a `message_3`;
* **handshakes:** as the initiator, given `initiator_seed`, the address
  of `responder_seed`, and as test hooks `initiator_ephemeral` and
  `c_i`, it sends `frames[0]`, then `frames[2]` on receiving
  `frames[1]`, and on receiving `frames[3]` derives `session_secret`;
  as the responder, given `responder_seed` and as test hooks
  `responder_ephemeral` and `c_r`, it sends `frames[1]` on receiving
  `frames[0]`, then `frames[3]` on receiving `frames[2]`, learning the
  initiator's address, and derives `session_secret`;
* **not for me:** given `responder_seed` and `frame`, it sends nothing;
* **rejected:** with the receiver of message `message` of the named
  handshake in the state that handshake leaves it in, given `frame` in
  its place, it sends nothing and derives no session.

Erasure cannot be checked by vectors. It is checked by reviewing an
implementation.

Each handshake also gives intermediate values (both addresses, `G_X`,
`G_Y`, `G_RX`, the contact tags, `TH_2` to `TH_4` and `PRK_out`) to
help find where an implementation goes wrong.

## Rationale

**EDHOC, method 3.** EDHOC is a published standard designed for
constrained radios, with published traces to test against. Method 3
authenticates with Diffie-Hellman keys and an 8-byte MAC instead of
64-byte signatures. For first contact that makes the frames 45, 53 and
73 bytes, against 45, 110 and 130 with signatures, which saves about
3.6 s of airtime per handshake at SF12/125 kHz
([analysis](../analysis/first-contact-fit.md)).

**Ed25519 addresses, converted for key agreement.** A node will need to
sign some things that are not sent to one peer, such as announces, so
its address needs to be a signing key. Method 3 needs a Diffie-Hellman
key. Converting one into the other gives a node one key and one address
for both purposes. The conversion is the one libsodium provides
(`crypto_sign_ed25519_pk_to_curve25519` and
`crypto_sign_ed25519_sk_to_curve25519`). Using one key for both purposes
is not a standard construction, and is the main thing a cryptographer
needs to review. The alternative is two keys per node, and an address
that names both.

**The credential carries the Ed25519 key.** `U(A)` loses the sign of
`A`'s x-coordinate, so an address and its negation have the same X25519
key. Carrying `A` itself in `CRED_I`, which the MAC covers, binds the
handshake to one address. Only the holder of a key can use either
address, so the shared X25519 key gives nobody else anything.

**The responder by `kid`, the initiator by value.** The initiator
already knows the responder's address, so the responder has nothing to
send, and its identity never goes on the air. The responder may never
have heard of the initiator, so the initiator sends its address. It is
encrypted, in `message_3`. Two nodes that have met before could save
45 bytes of `message_3` by naming the initiator by `kid`; that is left
for later.

**Contact tags from `G_RX`.** `message_1` has to tell its recipient that
it is for it. A tag made from the recipient's address would tell anyone
who knows that address too. One made from `G_RX` can be computed only by
the two ends. It costs the responder one X25519 for every `message_1` it
hears, whoever it is for. That cost is bounded by the airtime others
can spend sending them, but a node may still need to limit it (see
below).

**`message_4` always.** EDHOC needs `message_4` when the responder sends
nothing protected afterwards, and Tern does not yet define an
acknowledgement that could take its place. Without it, an initiator
whose `message_3` was lost would send unicast frames that are never
accepted. It costs one 17-byte frame. A later draft may let the
responder's first unicast frame stand in for it.

**No error messages.** They cost airtime. Silence also means a node
reveals nothing about itself to an initiator that fails, not even
whether it exists.

**No EAD.** Nothing in draft 0 needs it. A receiver that rejects it
keeps the message lengths fixed, and padding is undecided, as it is for
unicast frames.

**Exporter label 32768.** RFC 9528 reserves 32768 to 65535 for private
use. Tern will register a label of its own if the specification is
published as a standard.

## Not yet specified

* **Which settings first contact uses in each region.** Under a 400 ms
  dwell limit it needs SF8 or faster at 125 kHz, and under CN470's
  1 s limit, SF10 or faster
  ([analysis](../analysis/first-contact-fit.md)). This belongs with the
  region profiles.
* **Retransmission and timeouts:** how long a node waits before sending
  a frame again or giving up a handshake.
* **Delivering first-contact frames** to a responder whose address they
  do not show: `hop` and `label`, which the routing layer defines.
* **Limits on handshakes** a node will respond to, against nodes that
  send `message_1` to make it compute.
* **A shortcut for nodes that have met before.**
* **Measured cost on the nRF52840:** X25519, and a handshake from end to
  end.
