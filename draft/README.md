# Draft sections

Sections of the specification that are written ahead of the v0 draft
(MSH-30). The first three do not depend on the routing decision; the
next two write down the design the simulator measured, for that
decision to be made on; the two after carry a frame to every node and
say what a group's is; the last is the link between a node and the
client driving it, which never goes over LoRa. Positions travel in
the frames that carry messages. Each is a
**strawman**: complete enough to implement and test against, written to
be argued with, and not yet frozen. They move into the specification
proper when v0 is assembled.

| Section | What it covers | Vectors |
|---|---|---|
| [unicast-security.md](unicast-security.md) | The secured unicast frame: layout, keys, the blinded destination tag, sending and receiving | [`vectors/unicast-security.json`](../vectors/unicast-security.json) |
| [first-contact.md](first-contact.md) | Addresses, and the EDHOC handshake that gives two nodes a session: profile, frames, contact tags | [`vectors/first-contact.json`](../vectors/first-contact.json) |
| [phy.md](phy.md) | Radio settings: the sync word and the settings every frame uses, time on air, and a profile for each region, all provisional | [`vectors/phy.json`](../vectors/phy.json) |
| [routing.md](routing.md) | Routes: routing ids, announces, links judged by strength, loop-free route selection, requests, and when to announce | [`vectors/routing.json`](../vectors/routing.json) |
| [forwarding.md](forwarding.md) | Frames that follow routes: the head every such frame carries, passing a frame on, hearing that the next node has it, trying again and another way, and the acknowledgement a message's source waits for | [`vectors/forwarding.json`](../vectors/forwarding.json) |
| [flooding.md](flooding.md) | Frames for every node: the three-byte head, a frame's id, passing a frame on once after hearing whether others have, how far and how loud, and the share of its time a node gives to floods | [`vectors/flooding.json`](../vectors/flooding.json) |
| [groups.md](groups.md) | Groups: a shared secret, the frame one member writes for the rest, its random nonce and blinded tag, receiving, and the invite that hands a group over a session | [`vectors/groups.json`](../vectors/groups.json) |
| [companion.md](companion.md) | The companion protocol: how a phone or computer drives a node over USB serial, TCP or Bluetooth LE. Its frames, framing on a byte stream, the GATT profile, starting, syncing and versions. Never on the air | [`vectors/companion.json`](../vectors/companion.json) |
| [positions.md](positions.md) | Positions: where a user is, as a cell of a grid as coarse as they choose, sent only to the contacts and groups they choose, inside the frames that carry messages, and when | [`vectors/positions.json`](../vectors/positions.json) |
| [sharing.md](sharing.md) | Sharing an address off the air: how it is written down, the `ternmesh.org` link a QR code holds, and the short code two people compare. Never on the air | [`vectors/sharing.json`](../vectors/sharing.json) |
