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
   display draws at two pixels a module (58 of its 64 rows; see
   [Rationale](#rationale) for the margin round it).
3. **A code a phone's camera does something with.** The link is an
   ordinary web address, which every camera app offers to open, rather
   than a scheme only an installed app would claim.
4. **A check two people can do aloud.** Twelve digits that each
   person's device shows for an address, the same in every
   implementation, which differ for any other address with high
   probability.
5. **Nothing new on the air.** Every form here is made from the address
   alone, and none of them is sent over LoRa.

## Notation

`A` is a node's address, 32 bytes. `||` is concatenation; strings in
double quotes are their ASCII bytes, without a terminator. `X[i..j]` is
bytes `i` to `j - 1` of `X`. **Base32** is RFC 4648, section 6: the
alphabet `A` to `Z` and `2` to `7`, five bits a character, most
significant first. Here it is always written upper-case and without the
`=` padding, so 32 bytes are 52 characters, the last of which carries
one bit and four zero bits.

## The text form

An address is written as its 32 bytes in hexadecimal, most significant
digit of each byte first: **sixty-four digits, upper-case**, as
`D6D15FABBC42CE56...`. An implementation that shows an address MUST
show this form, and MAY put spaces between groups of digits to make it
easier to read.

An implementation that takes an address from a person MUST accept the
digits in either case, and MUST ignore spaces among them.

## The link

An address as a link is `HTTPS://TERNMESH.ORG/A/` followed by the
address in base32:

```
HTTPS://TERNMESH.ORG/A/23IV7K54ILHFMF2KINR6OV2DPJFHXL2CDNUQZKREM5XT6TYXZGLA
```

Seventy-five characters, all of them in the QR code's alphanumeric set
(digits, upper-case letters, space and `$%*+-./:`). An implementation
that shows an address as a QR code MUST encode the link, SHOULD use
alphanumeric mode, and then needs no larger than version 3 at error
correction level L, the lowest, which holds 77 such characters. A
larger version or a higher level is allowed. It SHOULD leave as wide a
light margin round the code as its display allows, up to the four
modules ISO/IEC 18004 asks for.

An implementation that reads a link MUST accept it with `HTTPS`, the
host `TERNMESH.ORG` and the `A` each in either case, and the base32 in
either case. Either case means ASCII's: a reader MUST refuse any
character outside ASCII, even one a Unicode case mapping turns into an
ASCII letter (`ı` into `I`, `ſ` into `S`). It MUST also accept the [text form](#the-text-form) alone,
so that digits pasted from a screen can be read. It MUST refuse
anything else, including another scheme or host, base32 of any other
length or with any other character, and base32 whose last character's
four low bits are not zero: each address has exactly one link. It MUST
check that an address it has read is [valid](first-contact.md#addresses)
before it keeps it as a contact. Reading a link MUST NOT need the
network: everything in the address is in the link.

**What is at the link.** A browser that opens it fetches a page from
`ternmesh.org` that reads the address out of the link and shows it, as
the text form and with its short code, for the person to copy into
whatever is to make contact. An app MAY claim the link, as Android's App
Links and iOS's universal links allow, and then opens it itself, with no
request made.

**What opening it tells the site.** The address is in the link's path,
and so is in the request a browser makes for the page: `ternmesh.org`
learns which address the person who opened it was looking at, and from
where. The site keeps no request logs and the page sends nothing on, but
that is a promise about one server, not something the protocol can
enforce. An implementation that shows a QR code SHOULD say, wherever it
explains the code, that a phone without a Tern app will open a web page.

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
  short code; and it reads `address` from each of `reads`. `base32` is
  the address in base32, the end of `link`;
* **refused:** it reads no address from any of `refused`;
* **not contacts:** it reads each `link` in `not_contacts`, and refuses
  to keep the address as a contact: each is one of
  [first contact's](first-contact.md#conformance) rejected addresses;
* **short code forms:** it shows each `value`, as a code, as `text`.

A QR code's modules are not given: encoders may choose different masks,
and every mask decodes to the same link.

## Rationale

**Hex, and upper-case, for the text form.** Hex is what every tool
already prints for a key, and what a person reads out most reliably, so
it is the form shown on a screen and printed on a console.

**A web address in the code.** A phone's camera app acts on a QR code
only when it knows what the text in it is. Draft 0 put `TERN:` and the
hex in the code, and a phone that scanned it reported no usable data: no
app had claimed the scheme, so the camera had nothing to offer. A web
address is something every camera opens. It also lets an app take the
link over once one exists, through App Links and universal links,
without any change to the code a node shows.

**Base32, for the link.** The code has to stay a version 3 code, the
largest a 64-pixel screen draws at two pixels a module; that holds 77
alphanumeric characters. `HTTPS://TERNMESH.ORG/A/` is 23 of them, which
leaves 54 for the address: hex needs 64, base32 52. Base32's alphabet is
inside the QR code's alphanumeric set and safe in a URL's path, and
RFC 4648 already defines it, so no implementation invents its own. The
link is upper-case because the alphanumeric set has no lower-case
letters; schemes and hosts are not case-sensitive, and the site serves
`/A/` and `/a/` alike.

**In the path, not after a `#`.** A fragment would keep the address on
the phone: browsers do not send what follows `#`. But `#` is not in the
alphanumeric set, so it would need a byte-mode segment of its own, and
the link split that way is 442 bits against version 3's 440. The path
costs the privacy said above; the next version up does not fit the
screen.

**One letter of path.** `A` leaves the site's other paths free, and two
of the 77 characters to spare.

**The margin a small screen leaves.** ISO/IEC 18004 asks for a light
margin, the quiet zone, four modules wide on every side. A version 3
code with that margin is 37 modules square: 74 pixels at two a module,
more than a 64-pixel screen has, and a version 3 code at one pixel a
module is too small for most phone cameras to resolve at arm's length.
So a 64-pixel screen draws the code at two pixels a module with the
margin it has room for, three pixels (a module and a half) above and
below. That is short of the standard; common decoders read it, as the
Heltec V3 port's tests check against ZXing and OpenCV, but a reader is
not promised to, and a display with room for the full margin should
give it. A version 2 code would fit with its margin, but holds 47
alphanumeric characters, too few for an address.

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
* **The site's files for App Links and universal links**
  (`assetlinks.json`, `apple-app-site-association`), which name the apps
  allowed to claim the link. They come with the apps.
