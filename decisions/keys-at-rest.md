# Keys at rest

**Status:** proposed, not decided. This memo lays out the choices and recommends some of them. It
enables nothing. Line references are to `ternmesh/firmware` at `76861e9`.

## The question

A node keeps its secrets in plain text in flash. Should the project turn on what the chips offer to
protect them: flash or NVS encryption on the ESP32, and APPROTECT on the nRF52840? And what would
each cost the people who reflash, recover and develop on these boards?

## What a node keeps, and where

The same records are kept on every port, through `plat_store_*` (`ports/node/node.c:408-416`):

* the identity seed, which is the node's address and everything it signs
  (`ports/node/demo.c:184-205`);
* the keys of its sessions;
* its groups' secrets;
* its contacts;
* writers' counters;
* the stored-ahead announce number and the routing `seq`;
* held cards;
* stored messages;
* its settings, including the Bluetooth passkey.

Where they live:

| | ESP32 (classic and S3) | nRF52840 |
|---|---|---|
| Store | ESP-IDF NVS, namespace `tern`, partition `nvs` at `0x9000`, 24 KB (`ports/esp32/partitions.csv`) | Zephyr settings on NVS, `storage_partition` at `0xEC000`, 32 KB |
| Encrypted | No flash encryption, no NVS encryption (`ports/esp32/README.md:349-350, 625`) | No |
| Readout protection | None. Anyone with USB can run `esptool read_flash` | The project sets nothing: Zephyr's default `CONFIG_NRF_APPROTECT_USE_UICR`, and whatever the board maker wrote to UICR. **Not checked on shipped boards** |
| Bluetooth bonds | NVS | settings `bt/` |
| Erase | Whole partition (`platform.c:74-102`) | Whole partition (`platform.c:123-149`) |

The firmware's release notes already say: "Saved messages and keys are not encrypted, a group's
secret among them" (`docs/releases/v0.5.0-alpha.3.md:54-55`).

## Who this is about

What encrypting at rest can do depends on who holds the node:

1. **Someone who finds or takes a node and reads its flash.** On ESP32 that takes a USB cable and a
   minute with esptool. On nRF52 it can be done by copying an image to the UF2 drive (no
   signature, see [signed-firmware-updates.md](signed-firmware-updates.md)) that dumps the storage
   partition. A UF2 copy writes only the blocks it carries, so the settings survive it. It may also
   be possible through the bootloader's `CURRENT.UF2`, if that file covers the storage partition,
   which has not been checked.
2. **Someone who can install firmware remotely** (threat 1 of the update memo). Their image runs
   with the application's own access and reads every key in the clear, **whatever encryption at
   rest is on**: transparent flash decryption and the NVS key belong to whatever code is running.
3. **A lab attacker** with fault injection. Published voltage-glitching attacks recover keys from
   the eFuses of classic ESP32 silicon before revision 3 (2019), and get around APPROTECT on
   nRF52840 revisions before revision 3 (2020). Nordic and Espressif both issued notices.

Encryption at rest addresses only case 1, and only if case 2 is closed first, and only for as long
as the attacker cannot simply install their own firmware over USB. Without Secure Boot they can.

## Options

| | What | Protects against | Irreversible? | Effect on reflashing, recovery and development |
|---|---|---|---|---|
| K1 | **ESP32 flash encryption**, release mode | 1, if Secure Boot is on too. Without it, an attacker flashes an image that reads the flash with the chip's transparent decryption | **Yes.** An eFuse key; release mode cannot be undone. Development mode can be turned off only a few times (`FLASH_CRYPT_CNT`) | Release mode: no plain-text flashing over USB, so the web flasher, other firmware and the user's own builds are gone; updates only over the air. Every image must be encrypted on the device or by the tooling. Recovery of a broken board over USB is limited |
| K2 | **ESP32-S3 NVS encryption, HMAC scheme.** The NVS keys come from an eFuse key that only the HMAC peripheral can use. No flash encryption is needed | 1, against a flash dump only. An attacker who flashes their own application derives the same keys from the same peripheral | **Partly.** One eFuse key block is burned for HMAC and can never be read or changed. Flashing stays open | The partition table changes (an `nvs_keys` partition, or the HMAC key ID in config), so existing nodes need a one-time USB reflash or an in-application migration. Not possible on the classic ESP32, which has no HMAC peripheral: there it needs K1 |
| K3 | **nRF52840 APPROTECT** (UICR, or `CONFIG_NRF_APPROTECT_LOCK`) | 1 through SWD only | Reversible: `ERASEALL` over SWD wipes the chip, keys included, and opens the port | None for UF2 or Bluetooth DFU, which go on working, and so does the UF2 route in 1. SWD recovery then means a full erase, then the bootloader, SoftDevice and application flashed again by debugger. Pointless while the UF2 bootloader takes unsigned images |
| K4 | **Application-level encryption under a user passphrase**, entered from the phone at each start | 1 and 3 (the key is not on the device) | No | A node that restarts unattended, such as a relay on a hill, cannot rejoin until someone unlocks it. That breaks relays |
| K5 | **Keep less at rest** | Limits what any capture gives | No | None. The specification already makes nodes erase the session secret `S` and old epoch keys ([unicast-security.md](../draft/unicast-security.md#keys)). Check that the firmware does, and cap stored messages. Add a "wipe" request to the companion protocol, and wipe on a factory-reset gesture |
| K6 | **Say what capture costs, and be able to recover from it** | No technical protection, but lets users act | No | A capture gives up the identity: contacts need a way to learn that an address is no longer its owner's. Identity revocation or rotation is not specified anywhere yet |

How these interact with the update memo:

* Encrypting at rest is worth nothing while threat 2 is open. The update memo's "now" items close
  it on ESP32, and only reduce it on nRF52.
* K1 or K2 without Secure Boot stop the casual dump of a lost node (1) and no more.
* Secure Boot plus K1 is the only combination that stops a person holding an ESP32 node. It is
  the "operator lock" the update memo describes: irreversible, and owner-hostile as a default.
* On nRF52 nothing at rest helps until the bootloader checks signatures and the UF2 drive is gone
  (update memo D). At that point K3, on revision-3 silicon, completes the chain.

## Recommendation

1. **Enable nothing irreversible by default.** K1 and Secure Boot would take control of a board
   away from its owner for ever and break the web flasher and every other route people reflash
   by. A Tern node has no secret worth that trade by default. Offer them, documented and opt-in,
   as the "operator lock" for unattended infrastructure.
2. **Do K5 now.** Check that erasure happens as the specification requires. Cap and expire stored
   messages. Add a client-initiated wipe. This is cheap and reduces what any capture gives,
   including through a remote compromise.
3. **Do K6 now, in words.** State in the specification and in user documentation that **anyone
   who holds a node can read its identity, sessions, group secrets and messages**. Open a
   specification item for identity revocation, which every capture eventually needs.
4. **Consider K2 on ESP32-S3** once signed updates (update memo, "now" items 1 to 3) have shipped,
   since it does not lock flashing and stops the one-minute dump. Weigh it against the cost of
   migrating partition tables on deployed boards, and against what it actually stops: a casual
   finder, not a determined one. Not on the classic ESP32.
5. **Leave K3 off** until the nRF52 boards have a bootloader that checks signatures. Before that
   decision, check what APPROTECT state shipped boards actually have (`nrfjprog --readregs`, or
   SWD access, on each board family), so that the documentation states it correctly.

What Tern could then honestly say:

> A node does not protect its keys from someone who holds it. Losing a node means its identity, and
> the groups it belonged to, should be treated as compromised.

## What would reopen this

* Boards with a secure element, or chips with key storage that firmware cannot read out (for
  example the nRF5340's KMU).
* Signed updates with a signature-checking bootloader on every port, after which encrypting at rest
  stops being undone by installing an image.
* A deployment that wants the operator lock as its default.
