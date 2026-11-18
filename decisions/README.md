# Decisions

Choices about the project that are not part of the protocol: which
implementations it keeps, where they live, and why. The specification's
own reasoning stays in each section's **Rationale**; this directory is for
the rest, so that it is recorded alongside the specification rather than
only in chat (see [GOVERNANCE.md](../GOVERNANCE.md#who-decides)).

| Decision | What it settles |
|---|---|
| [phone-apps.md](phone-apps.md) | Phone apps are native per platform, each written from the companion protocol and checked against its vectors |
| [signed-firmware-updates.md](signed-firmware-updates.md) | **Proposed, not decided.** Who may give a node firmware, and what checks that an image is the project's |
| [keys-at-rest.md](keys-at-rest.md) | **Proposed, not decided.** Whether to encrypt what a node keeps in flash, and what that would cost |

A proposal is merged here only once it is decided, with its status changed to say so; until then
it is open for review in its pull request.
