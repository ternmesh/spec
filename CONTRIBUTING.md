# Contributing to the Tern specification

Thank you for helping. Before you open a pull request, read
[GOVERNANCE.md](GOVERNANCE.md), which explains how decisions are made.

## Sign your commits (DCO)

Tern uses the [Developer Certificate of Origin](DCO) instead of a
contributor licence agreement. You keep the rights to your work; you
certify that you are allowed to contribute it under this repository's
licences.

Add a `Signed-off-by` line to every commit with your real name and an
email address you control:

```bash
git commit -s -m "Clarify slot guard time"
```

which adds:

```
Signed-off-by: Your Name <you@example.org>
```

Pull requests with unsigned commits cannot be merged. To sign commits
you have already made: `git rebase --signoff main`.

## What you are licensing

| Path | Licence |
|---|---|
| Specification text (everything outside `vectors/`) | [CC-BY-4.0](LICENSE) |
| `vectors/` — conformance test vectors | [CC0-1.0](vectors/LICENSE) |

Test vectors are public domain so that any implementation, under any
licence, can include them without attribution requirements.

## Writing specification text

* **Normative requirements must be testable.** If a conformance test cannot
  check it, it belongs in the rationale, not the specification.
* Use the key words MUST, SHOULD and MAY as described in RFC 2119 and
  RFC 8174, and only in their capitalised form.
* A change to wire format or behaviour comes with test vectors in
  `vectors/` for the new behaviour.
* Say why. A change describes the problem it solves and the alternatives
  that were considered.

## Clean-room rule

Tern interoperates with other mesh protocols only through gateways that
work at the application layer. When describing another protocol's wire
format, work from published documentation and observed packets. **Do not
copy source code or text from other implementations** into this repository.
