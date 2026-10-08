# Phone apps: native per platform

**Decided:** the phone apps are written natively for each platform, each
implementing the [companion protocol](../draft/companion.md) from the
specification:

| App | Repository | Platforms | Language |
|---|---|---|---|
| Apple | `ternmesh/apple` | iPhone, iPad and Mac | Swift and SwiftUI |
| Android | `ternmesh/android` | Android | Kotlin |

Each passes [`vectors/companion.json`](../vectors/companion.json) in its own
CI. Neither depends on another implementation's code.

## Why

**The vectors are the shared part.** Writing the protocol twice costs two
implementations that can drift apart. The companion vectors already pin
down what drifts: the frames, what a client ignores, the stream framing and
an exchange from HELLO through a sync. An app that runs them in CI agrees
with every other implementation that does, which is the same promise
[GOVERNANCE.md](../GOVERNANCE.md) makes about compatibility in general.

**The protocol is small.** A frame is a type, a sequence byte and fixed
fields, at most 180 bytes, and the codec is one table. Over Bluetooth LE
there is no stream framing to write at all: one frame per write or
notification. What remains is the conversation (one request at a time,
answer and idle timers, counted news), which the draft states.

**One language per app.** A contributor to the Apple app needs Swift, and
one to the Android app needs Kotlin; neither needs C, a bridge to it, or
another project's build.

**The apps belong to the project.** They live under `ternmesh`, with no
dependency on a repository held by an individual.

## Alternatives considered

**A shared C core under native screens.** One implementation of the
protocol, compiled into both apps (directly from Swift; through JNI on
Android). Rejected for now: the existing C implementation, in
`mcereal/mesh-client`, stores what it learns in that client's own model
and runs on that client's event loop, so sharing it would mean carrying
much of that client into each app and holding its internals stable for
them. Only its codec would come out cleanly, and the codec is the smallest
part. If the duplicated codec ever costs more than a dependency would, the
way back is a small standalone codec library under `ternmesh`, not another
client's core.

**A web app for Android, native for iPhone.** Chrome on Android has Web
Bluetooth; Safari has none. Rejected: a messaging app has to receive while
the phone is in a pocket, and background running and notifications are
where a web app is weakest. Web Bluetooth also gives a page no way to ask
for the ATT MTU the companion profile needs (at least 183), leaving that
to the browser.

## What would reopen this

* The companion protocol growing large enough that two implementations of
  it cost more to keep than one shared one.
* A maintainer for one platform who would rather share code, for example
  through Kotlin Multiplatform, and will keep it.
