# Governance

Tern is a LoRa mesh protocol. This document says who decides what, what
is promised to people who build on it, and how both change as the project
grows. It is written now, before there is anything worth capturing,
because that is the only time it is cheap to get right.

## What Tern is made of

| Part | Repository | Licence |
|---|---|---|
| The specification | [`ternmesh/spec`](https://github.com/ternmesh/spec) | [CC-BY-4.0](LICENSE) |
| Conformance test vectors | `ternmesh/spec/vectors/` | [CC0-1.0](vectors/LICENSE) |
| The simulator | [`ternmesh/sim`](https://github.com/ternmesh/sim) | Apache-2.0 |
| The reference implementation | [`ternmesh/firmware`](https://github.com/ternmesh/firmware) | Apache-2.0 |

**The specification is the protocol.** The reference implementation is one
implementation of it, with no special standing. Where the two disagree,
the specification wins, and the implementation is fixed or the
specification is amended in the open.

**Compatibility is defined by the conformance suite.** An implementation is
Tern-compatible if it passes the published conformance tests for the
profile it claims. Nobody's permission is required, including the
maintainers'.

The specification does not depend on any implementation language,
toolchain or vendor. An implementation written in any language by anyone
stands on equal terms.

## Commitments

These hold for the life of the project and are not subject to the
decision process below.

1. **The licences above are irrevocable for everything already published.**
   Nothing contributed under them will be relicensed.
2. **Contributions are made under the Developer Certificate of Origin, never
   a CLA.** No contributor assigns rights to any person or company. See
   [CONTRIBUTING.md](CONTRIBUTING.md).
3. **The name, the domain and the organisation are held for the project,
   not for a company.** "Tern" will not be registered as a trademark by any
   commercial entity, including one run by a maintainer. If it is
   registered, it is registered by a vendor-neutral fiscal sponsor, or by
   an individual with a recorded commitment to assign it to one. The same
   applies to the `ternmesh.org` domain and the `ternmesh` GitHub
   organisation.
4. **The specification stays free to implement.** No part of the
   specification will require a paid licence, a membership, or a
   certification fee to implement or to claim conformance.

## Who decides

**Today:** the project has a single maintainer, Michael Curtis
([@mcereal](https://github.com/mcereal)), who makes decisions and is
accountable for them in public.

Decisions are made in the open. A change to the specification is a pull
request against this repository with its reasoning in the description; it is
merged only after it has been public for at least seven days, except for
editorial fixes. The reasoning behind design choices is recorded alongside
the specification, not only in chat.

**As contributors arrive:** anyone with a sustained record of substantive
contributions to the specification, the conformance suite or an
implementation may be invited to become a maintainer. Once there are three
or more maintainers:

* specification changes need approval from at least two maintainers, at
  least one of whom did not author the change;
* maintainers are added by consensus of the existing maintainers;
* a maintainer from any single employer may not be a majority of the
  maintainers, once the project has maintainers from more than one
  employer.

## Where the project lives

Tern has its own home from the start, separate from any other project or
company its maintainers are involved in:

* the [`ternmesh`](https://github.com/ternmesh) GitHub organisation;
* the [`ternmesh.org`](https://ternmesh.org) domain.

Both are currently held by the original author on the project's behalf
(see Commitment 3). Once the project has maintainers from outside, they
choose together whether to move the name, the domain and the organisation
to a fiscal sponsor such as Software Freedom Conservancy, and when.

## Changing this document

Until there are three maintainers, this document changes by pull request,
public for at least fourteen days before merging. After that, changes need
the agreement of two thirds of the maintainers. The **Commitments** section
can be extended but not weakened.
