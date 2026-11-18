# Signed firmware updates

**Status:** proposed, not decided. This memo lays out the choices and recommends some of them.
Nothing here changes the specification or the firmware. Line references are to `ternmesh/firmware`
at `76861e9` and to this repository's `draft/companion.md`.

## The question

At the moment a Tern node will run any image it is given by anyone who can drive it, and on the
nRF52840 boards it will run an image from anyone in Bluetooth range while its bootloader is
waiting for one. What should check that an image was published by the project, and how much
irreversibility and brick risk is worth paying for that check?

## What happens today

**nRF52840 boards** (Heltec T114, RAK4631, Seeed Wio Tracker L1 and T1000-E) run a Zephyr
application. It sits on top of the Adafruit nRF52 bootloader, which is UF2 over USB plus Nordic's
legacy DFU (nRF5 SDK 11) over Bluetooth. The bootloader keeps a SoftDevice below the application
for its own use. Over Bluetooth only the "OTAFIX" build works
(`ports/nrf52/README.md:121-136`; `ports/nrf52/src/platform.c:397-417`), and the firmware detects
that build by finding the string `OTAFIX` in the bootloader's partition.

* A paired client sends `UPDATE_BOOTLOADER` (companion `0x36`, protocol 12;
  [companion.md](../draft/companion.md#by-the-bootloader)). The node writes `0xA8` to GPREGRET and
  restarts into the bootloader (`ports/nrf52/src/platform.c:389,419-424`).
* The bootloader takes a DFU package from **any** central in range. The only check is the init
  packet's CRC (`tools/ble_dfu.py:29`). Releases are built with
  `adafruit-nrfutil dfu genpkg --sd-req 0xFFFE`, with no key and no signature
  (`ports/nrf52/release.sh:47-51`).
* The specification asks a bootloader to keep waiting over Bluetooth after an update that breaks
  off part of the way, so that the user does not need a cable (companion.md, "By the
  bootloader"). An interrupted update therefore leaves the node open to anyone in range until
  some image arrives.
* Over USB, a double-tap of reset or a 1200-baud touch (`ports/nrf52/src/board.c:688-701`)
  brings up the UF2 drive, which takes any image dropped on it.
* The project has never built or replaced a bootloader. Users install the OTAFIX bootloader
  themselves from its own releases.

**ESP32 boards** (classic ESP32 and ESP32-S3, ESP-IDF 5.5) are updated over the companion
protocol itself (`UPDATE_BEGIN`/`DATA`/`END`), into the second of two OTA slots
(`ports/esp32/main/platform.c:306-383`). Before switching slots the node checks:

* the SHA-256 the client declared (`ports/node/link.c:1717-1782`);
* ESP-IDF's own image validation in `esp_ota_end`;
* that the image's project name, `tern-<board>`, matches the running image.

There is no signature check. App rollback is on (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`), so a
bad image falls back to the old one. Secure Boot is not enabled. The ROM serial bootloader always
accepts a new image over USB.

**Pairing.** Both characteristics require LE Secure Connections with passkey entry. Boards with a
screen show a fresh random passkey each time. Boards without one (RAK4631, T1000-E, Heltec Wireless
Stick Lite V3, Wireless Tracker, Vision Master E213, Wireless Paper, and any board whose screen
fails at start, `ports/node/node.c:3392-3399`) pair with the fixed passkey `123456` until the user
sets another with `SET` 4 (`ports/node/node.c:2979-2984`). A passkey that everyone knows gives no
protection against an attacker in the middle, and none against a stranger pairing first. The
USB serial link has no authentication at all.

## Threats, in order of how much they matter

1. **Someone in Bluetooth range installs their own firmware** on a node they have never touched.
   That is a total compromise: they get the identity key, every session, every group secret, and
   the stored messages. They can impersonate the node, leave a tracking beacon behind, or turn
   the node into a jammer. Three ways in exist today:
   * (a) On any board without a screen whose passkey has not been changed: pair with `123456`,
     then either update the node over the companion protocol (ESP32) or send `UPDATE_BOOTLOADER`
     and then the image (nRF52).
   * (b) On nRF52: win the race against the owner's client while the bootloader is waiting for
     the owner's image.
   * (c) On nRF52: after the owner's update breaks off, while the bootloader waits indefinitely.
2. **A tampered image reaches an honest user**, for example from a look-alike download site or a
   compromised release pipeline. The user's own client installs it.
3. **Someone holding the node** reflashes it over USB or SWD. Only Secure Boot can stop this, and
   [keys-at-rest.md](keys-at-rest.md) covers why that matters less than it seems.

Threat 1(a) is the cheapest to exploit and affects every port. Signing does not close it alone:
an attacker who can pair can drive the node, change its settings and read its messages without
installing anything.

## Options

| | Option | Stops | Cost | Risk / irreversibility |
|---|---|---|---|---|
| A | Sign releases, and have clients check the signature before sending an image | 2 | Low. A release key, a signature file per image, and a check in each app | None on devices |
| B | Check the signature on the node, in the application, before it switches to the new image (ESP32) | 1(a) and 2 on ESP32, through the companion path | Small. Ed25519 verify is already in the firmware (`include/tern/address.h`). The public key is compiled in. One companion-protocol field for the signature | None: the ROM bootloader and rollback are unchanged |
| C | Check the signature in the nRF52 application before restarting into the bootloader | Nothing | The image never passes through the application: the bootloader receives it straight from the client | Gives false confidence. Rejected |
| D | Replace the nRF52 bootloader with one that checks signatures: MCUboot (Zephyr's own), Nordic's Secure DFU (nRF5 SDK, ECDSA P-256), or a fork of Adafruit's with a check added | 1(b), 1(c) and 2 on nRF52; 3 too, once USB UF2 is gone | Large. A new flash layout (MCUboot needs two slots and no SoftDevice). Updates move to the companion path, as on ESP32. Each board must be tested | **Brick risk on boards already deployed.** Writing a new bootloader, the MBR and UICR from a running application can fail part-way, for example on power loss. Mending that needs SWD, and the T1000-E has no debug header (`ports/nrf52/boards/t1000_e/board.cmake:1`) |
| E | ESP32 Secure Boot v2 (RSA-3072 or ECDSA; needs revision-3 silicon on the classic ESP32) | 1, 2 and 3 on ESP32 | Small in code. A per-board provisioning step | **Irreversible eFuse burn.** The board then runs only images signed by the project's key: the owner can never again flash a build of their own, another Tern implementation, or another mesh's firmware. A lost key bricks every board for updates |
| F | Per-device random passkeys for boards without a screen: printed on a label, or shown over USB or by LED; or default-passkey pairing allowed only for a short window after a physical action (power-on or a button press) | 1(a) | Small, firmware only. Labels need a manufacturer, and Tern does not make boards | None. Users must press a button, or power-cycle the board, to pair the first time |
| G | No new bonds once a node has one, unless physically present or approved by a bonded client | 1(a) after the first pairing | Small | None. Recovery is clearing bonds over USB or on the node, as today |
| H | A bootloader that takes images only from the bonded client | 1(b) and 1(c) | The bootloader would need the application's bonds, or a one-time token passed in retained RAM: a bootloader change, so it costs what D costs | As D |
| I | Shorten the nRF52 window: drop "waits over Bluetooth after a failed update" from the specification; use dual-bank DFU so an interrupted transfer leaves the old application intact and the bootloader can time out back to it | 1(c) | A specification change, plus checking each bootloader's dual-bank behaviour. The current application (about 360 KB of 788 KB on T1000-E) still fits half the space | Some users with a failed update then need a cable, which is what the "SHOULD" was meant to avoid |

On D in more detail:
* The Adafruit bootloader updates itself with a self-update package that the running bootloader
  writes. That is the least risky route, and it is still a write of the region the chip boots
  from.
* Moving to MCUboot also replaces the MBR and SoftDevice layout. It is realistic for boards
  flashed over SWD (the factory, or developers). It is not realistic for a user's T1000-E over
  Bluetooth.
* `docs/boards.md:177-179` already lists "the two firmware slots MCUboot gives" as future work.

## Recommendation

**Now (no irreversible step, no bootloader change):**

1. **Sign every release (A).** Use an Ed25519 key held offline, with its public key in this
   repository and in the firmware. Add a detached signature to each release asset. The phone apps
   and `tools/companion.py` refuse an unsigned image unless the user says otherwise. This also
   gives the specification's "Signed firmware" item in companion.md its format.
2. **Check signatures on ESP32 nodes (B).** `UPDATE_END` refuses an image whose signature over
   its digest does not verify against a compiled-in key (one of a short list, so the key can be
   rotated). A developer setting turns this off; it can be changed only over USB, which already
   gives full control. esptool over USB keeps working, so nothing is lost for developers.
3. **Close the default-passkey hole (F + G).** A board without a screen accepts the default
   passkey only within a few minutes of a power-on or button press. Once a node has a bond, it
   takes new bonds only in such a window. Together these remove 1(a), the cheapest attack, on
   every port, and they also protect the node's messages, which signing does not.
4. **On nRF52, state the residual risk plainly and shorten it (I).** Say in the specification and
   in user documentation: "while the bootloader waits, anyone in range can install an image".
   Prefer dual-bank DFU with a timeout over waiting indefinitely.

**Later, with hardware in hand (D):** move the nRF52 boards to MCUboot with signed images and
updates over the companion protocol, the same path as ESP32, starting with boards flashed over SWD
and new production. Offer a USB-only migration for existing boards only after it has been tested
on each board, and never over Bluetooth. Not on T1000-E boards in the field.

**Not recommended as a default (E):** ESP32 Secure Boot. It permanently takes control of a board
away from its owner, and that conflicts with the project's commitment that anyone may implement
Tern and run it. Document it as an opt-in "operator lock" for infrastructure that will be left
unattended, such as a relay on a hill, with its irreversibility stated.

What Tern could then honestly say:

> Release images are signed. ESP32 nodes refuse unsigned updates, and no node pairs with a stranger
> without someone physically at it. nRF52 nodes still accept an unsigned image during the update
> window, until their bootloader is replaced.

## What would reopen this

* A bootloader for the nRF52 boards that checks signatures and can be installed in the field
  without a debugger.
* Board makers shipping per-device passkeys, or Secure Boot already provisioned.
* A deployment, such as unattended relays, that wants an irreversible lock and accepts its cost.
