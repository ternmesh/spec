# Tern specification

Tern is a LoRa mesh protocol designed around one idea: **airtime is a
shared, metered resource**. Its addresses are public keys, it gives each
node an airtime budget, and leaf nodes can sleep on a schedule.

This repository holds the specification and the conformance test
vectors. It is the definition of the protocol; implementations live
elsewhere.

**Status:** pre-draft. Routing is being decided by simulation
([ternmesh/sim](https://github.com/ternmesh/sim)) before any of it is
specified.

* [GOVERNANCE.md](GOVERNANCE.md) — who decides, what is promised, and when the project moves
* [CONTRIBUTING.md](CONTRIBUTING.md) — DCO sign-off and how to write spec text
* [draft/](draft/README.md) — sections written ahead of v0: [secured unicast frames](draft/unicast-security.md), [first contact](draft/first-contact.md), provisional [radio settings](draft/phy.md), a strawman of [routes](draft/routing.md) as the simulator measured them, [frames for every node](draft/flooding.md) and the [groups](draft/groups.md) that send them, the [companion protocol](draft/companion.md) a phone or computer drives a node with, how an address is [shared off the air](draft/sharing.md), and how a user shares their [position](draft/positions.md) with whom they choose, and the [presence cards](draft/cards.md) that let people nearby find each other without a public channel
* [decisions/](decisions/README.md) — choices about the project that are not protocol, starting with [native phone apps](decisions/phone-apps.md)
* `vectors/` — conformance test vectors
* [analysis/](analysis/) — questions the specification needs answered, worked from public sources, starting with [whether first contact fits one frame](analysis/first-contact-fit.md)

## Licence

The specification is licensed under [CC-BY-4.0](LICENSE). The test vectors
in `vectors/` are dedicated to the public domain under
[CC0-1.0](vectors/LICENSE).
