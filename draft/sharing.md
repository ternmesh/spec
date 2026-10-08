# Sharing an address

**Status:** strawman, draft 0. Not frozen. Open for review under the
seven-day rule in [GOVERNANCE.md](../GOVERNANCE.md). Nothing here goes
over the air.

A node's [address](first-contact.md#addresses) is 32 bytes that the
protocol never sends in clear, so it reaches another person some other
way: read off a screen, scanned from a QR code, or sent as a link. This
section defines the forms an address takes when it does, so that what
one implementation shows, every other reads, and the **short code** two
people compare to check that they have the address they meant to.

Test vectors: [`vectors/sharing.json`](../vectors/sharing.json),
produced by [`vectors/tools/sharing.py`](../vectors/tools/sharing.py).

## Goals

1. **One way to write an address down,** so a node's screen, a phone
   app and a command line all show and take the same thing.
2. **A QR code that is small enough for a node's screen.** The link
   below fits a version 3 code, 29 modules square, which a 128 by 64
   display draws at two pixels a module.
3. **A check two people can do aloud.** Twelve digits that each
   person's device shows for an address, the same in every
   implementation, which differ for any other address with high
   probability.
4. **Nothing new on the air.** Every form here is made from the address
   alone, and none of them is sent over LoRa.

## Notation

`A` is a node's address, 32 bytes. `||` is concatenation; strings in
double quotes are their ASCII bytes, without a terminator. `X[i..j]` is
bytes `i` to `j - 1` of `X`.

## The text form

An address is written as its 32 bytes in hexadecimal, most significant
digit of each byte first: **sixty-four digits, upper-case**, as
`D6D15FABBC42CE56...`. An implementation that shows an address MUST
show this form, and MAY put spaces between groups of digits to make it
easier to read.

An implementation that takes an address from a person MUST accept the
digits in either case, and MUST ignore spaces among them.

## The link

An address as a link is `TERN:` followed by its text form:

```
TERN:D6D15FABBC42CE56174A4363E757437A4A7BAF421B690CAA24676F3F4F17C996
```

Sixty-nine characters, all of them in the QR code's alphanumeric set
(digits, upper-case letters, space and `$%*+-./:`). An implementation
that shows an address as a QR code MUST encode the link, SHOULD use
alphanumeric mode, and then needs no larger than version 3 at error
correction level L, the lowest, which holds 77 such characters. A
larger version or a higher level is allowed.

An implementation that reads a link MUST accept the scheme in any case
(`TERN:`, `tern:`) and the digits as the text form allows. It MUST also
accept the text form alone, without the scheme, so that a code made
before this section, or digits pasted from a screen, can still be read.
It MUST refuse anything else, including `TERN://` and digits of any
other count. It MUST check that an address it has read is
[valid](first-contact.md#addresses) before it keeps it as a contact.

## The short code

```
H     = SHA-256("tern short code" || A)
n     = H[0..8], as a big-endian unsigned 64-bit integer
code  = n mod 10^12
```

shown as **twelve decimal digits, leading zeros kept, in three groups of
four**: `5358 3737 3382`. Every implementation that shows a short code
MUST show this one, and SHOULD show it wherever it shows an address for
someone to check.

It is for two people with their devices side by side, or on a call: one
reads the code their node shows for itself, the other checks it against
the code their phone shows for the address it scanned or was sent. If
they match, the phone has the address of the node in front of them.

## Conformance

An implementation conforms to this section if, for every case in
[`vectors/sharing.json`](../vectors/sharing.json):

* **cases:** given `address`, it shows `text` as the text form, encodes
  `link` in any QR code it makes of it, and shows `short_code` as its
  short code; and it reads `address` from each of `reads`;
* **refused:** it reads no address from any of `refused`;
* **short code forms:** it shows each `value`, as a code, as `text`.

A QR code's modules are not given: encoders may choose different masks,
and every mask decodes to the same link.

## Rationale

**Hex, and upper-case.** Hex is what every tool already prints for a
key, and upper-case hex is in the QR code's alphanumeric set, which
packs 5.5 bits a character against byte mode's 8. The link in byte mode
would need version 4, 33 modules square, which a 64-pixel screen can
draw only at one pixel a module. A denser alphabet (base32, base58)
saves a version but not a size worth having, and is one more thing to
get right in every implementation.

**A scheme.** A QR code holding bare hex is just text to a phone. With
a scheme, an app can register for `tern:` links and be opened by them,
and a reader can tell an address from any other sixty-four digits. The
colon form (`TERN:`, not `tern://`) is what `mailto:` and `tel:` use for
something with no host, and the colon is in the alphanumeric set.
Readers accept bare digits too, so that nothing written before this
section is lost.

**Twelve digits.** The code has to be short enough to read aloud and
long enough that nobody can make an address whose code matches
another's. Bluetooth's numeric comparison gets by with six digits
because both sides commit before either shows its number; here one side
shows its code to anyone, so an attacker can search for a key whose
address gives the same code. Twelve digits are just under 40 bits: a
match takes about 10^12 tries, each an Ed25519 key pair and a hash. At
some hundred thousand key pairs a second on one processor core, that is
over a hundred core-days for one victim, against the ten seconds six
digits would take; it is well within reach of someone who rents the
machines or uses graphics processors, which is why the code is a check
against mistakes and casual impersonation, and the full address, in the
QR code, is the strong one (see [Not yet specified](#not-yet-specified)).
Signal's safety numbers, 60 digits for a pair of people, protect more
and are not read aloud.

**Decimal, in fours.** Digits read the same in every language and on
every keypad, and groups of four are the size people already read out
for card numbers and codes.

**Its own label.** `"tern short code"` keeps the code apart from the
[routing id](routing.md#routing-ids), which is a hash of the same
address that does go over the air. Knowing one gives nothing towards
the other.

**The first eight bytes, reduced.** 2^64 is not a multiple of 10^12, so
the low codes are more likely than the high by about one part in
eighteen million. That bias is of no use to anyone.

## Not yet specified

* **A name in the link.** Names are local: a node never sends one. A
  link that carries a suggested name, for the person scanning it to
  keep or change, needs byte mode for anything but upper-case ASCII, and
  so a larger code than a node's screen draws well.
* **Making the search harder.** Iterating the hash, as Signal does for
  its fingerprints, would cost a phone nothing and a node a fraction of
  a second, and would put a match out of reach rather than days away.
  Worth it if the short code ends up protecting more than a mistake.
* **Where a phone app gets the address from.** Scanning, a link and
  pasting are covered. Sending a node's address over the companion link
  to another phone is not.
