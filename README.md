# Strider Repolished (NES)

Small fixes and improvements to Strider (NES), trying to make the game feel more polished without drastic alterations to its look and feel.
Mapper and romsize have been kept deliberately identical to the original.

Tested on emulators and MiSTer FPGA.

Please report any bugs, and feel free to suggest improvements, especially regarding triangle jump timing and jump height.

**Current release: v0.8b** — [`patch/Strider Repolished v0.8b.ips`](patch/)

## Gameplay changes

- Tile loading behavior: garbled tiles on spawning enemies are dramatically reduced.
- Variable jump height: keeping A pressed makes Hiryu jump as high as in the original game, faster presses makes his jump height shorter.
- Walls no longer stop your jumping momentum, Hiryu does not clip in them by walking, knockback "teleportation" is also fixed.
- Triangle jump timing is much more lenient.

## Other changes

- Save system added in place of Password.
- Revised English translation, based on the Japanese prototype.
- Slowdown does not affect music playback.
- Health pills do not jiggle on the ground.
- Attract mode is now a skippable intro.
- "NEXT EPISODE" text is skippable.

## Known issues

- On slopes, pills spawn slightly below ground (they are still collectable).
- Save screen still shows the password.
- Jump physics when hitting a ceiling behave like the original game, this is needed for certain platforming sections. Could be eliminated by fine-tuning the variable jump height.
- When hitting a ceiling while jumping, Hiryu's head is not fully outside it.

## Applying the patch

Apply the IPS patch (Flips, Lunar IPS, RomPatcher.js, …) to an unmodified copy of the US ROM:

| | |
|---|---|
| File | `Strider (USA).nes` (iNES header, 262,160 bytes) |
| CRC32 (with header) | `5307702A` |
| SHA-1 (with header) | `a91cf3ff63dd7a45c8c83bc0e192c1011d217609` |
| SHA-1 (without header) | `1df12a7b72f3d2a0c506216acf8acc0a81b923f7` |

Patched result: CRC32 `13A3651A`, SHA-1 `74a4212a4d37d58e343d970d5dcc90dab2eff461`, same size.

No ROM is included in this repository; you need your own.

### Cartridge / emulator

The patched ROM is still the original cartridge type — MMC1, 256K PRG-ROM, 8K CHR-RAM — now with 8K of
**battery-backed PRG-RAM** (the SNROM board with a battery, as used by *The Legend of Zelda*). It carries an
NES 2.0 header declaring that RAM. Any emulator or flash cart that supports SNROM with a battery should run it.
Without the cartridge RAM the sprite fix switches itself off and the game behaves like the original.

## Building from source

Requirements: Python 3.8+ and your own `Strider (USA).nes`.

```
python src/build.py "Strider (USA).nes" --retime --glue --preload
```

writes `build/Strider Repolished [title retime + ceiling glue + enemy tiles preload].nes`. Without flags you get the
base build (modern ceiling handling, no level pre-load, original title timing). Other options:
`--skip <patch,...>` to leave patches out (e.g. `--skip feel` for the original jump feel, `--skip save`,
`--skip music`, `--skip nskip`), `--only <patch,...>`, `--out <file>`.

All patches are commented 6502 assembly inside `src/build.py`, assembled by the small assembler in
`src/asm6502.py`. `src/make_ips.py original.nes patched.nes out.ips` writes an IPS patch.

The revised script text is **not** part of this repository. Without `src/revised.json` the build skips the text
patch and keeps the original text (so it will not match the release patch byte for byte). The message-table data
the text patch needs is extracted from your ROM at build time (`src/build_entries.py`).

## Credits
- Displaced Gamers' *Behind the Code* videos on Strider's garbage sprites and jumping physics, which explained the
  original bugs this project started from.
- The *Strider Script Revision* fan project for the revised English text.

## License
The patch source code in this repository is released under the [MIT License](LICENSE). It does not cover
the game itself or the revised script text.

## Disclaimer
Strider is © Capcom. This is an unofficial fan patch, not affiliated with or endorsed by Capcom or Nintendo.
This repository contains no ROM images or extracted game assets: only patch source code and an IPS patch to apply to your own copy.
