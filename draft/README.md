# Draft sections

Sections of the specification that are written ahead of the v0 draft
(MSH-30) because they do not depend on the routing decision. Each is a
**strawman**: complete enough to implement and test against, written to
be argued with, and not yet frozen. They move into the specification
proper when v0 is assembled.

| Section | What it covers | Vectors |
|---|---|---|
| [unicast-security.md](unicast-security.md) | The secured unicast frame: layout, keys, the blinded destination tag, sending and receiving | [`vectors/unicast-security.json`](../vectors/unicast-security.json) |
| [first-contact.md](first-contact.md) | Addresses, and the EDHOC handshake that gives two nodes a session: profile, frames, contact tags | [`vectors/first-contact.json`](../vectors/first-contact.json) |
| [phy.md](phy.md) | Radio settings: the sync word and the settings every frame uses, time on air, and a profile for each region, all provisional | [`vectors/phy.json`](../vectors/phy.json) |
