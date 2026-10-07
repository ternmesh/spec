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
* [draft/](draft/README.md) — sections written ahead of v0: [secured unicast frames](draft/unicast-security.md), [first contact](draft/first-contact.md), provisional [radio settings](draft/phy.md), and a strawman of [routes](draft/routing.md) as the simulator measured them
* `vectors/` — conformance test vectors
* [analysis/](analysis/) — questions the specification needs answered, worked from public sources, starting with [whether first contact fits one frame](analysis/first-contact-fit.md)

## Licence

The specification is licensed under [CC-BY-4.0](LICENSE). The test vectors
in `vectors/` are dedicated to the public domain under
[CC0-1.0](vectors/LICENSE).
