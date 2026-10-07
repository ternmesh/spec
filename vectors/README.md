# Conformance test vectors

Inputs and the exact bytes or behaviour a conforming implementation must
produce from them. **Passing these is what "Tern-compatible" means** — see
[GOVERNANCE.md](../GOVERNANCE.md).

Everything in this directory is dedicated to the public domain under
[CC0-1.0](LICENSE), so any implementation under any licence can carry it.

| File | Section | Generator |
|---|---|---|
| `unicast-security.json` | [Secured unicast frames](../draft/unicast-security.md) | `tools/unicast.py` |
| `first-contact.json` | [First contact](../draft/first-contact.md) | `tools/first_contact.py` |
| `phy.json` | [Radio settings](../draft/phy.md) | `tools/phy.py` |

Each file is the output of its generator, and CI fails if the two
disagree. To change a vector, change the generator and run it with
`generate`; `check` confirms the file matches. The first two generators
need the Python `cryptography` package, and check it against published
RFC vectors before computing anything. `tools/phy.py` needs nothing, and
checks its arithmetic against values worked by hand.
