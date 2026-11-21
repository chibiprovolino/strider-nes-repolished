# Strider Repolished (NES)

A bug-fix and polish patch for **Strider** (NES, Capcom, 1989, US release).

It fixes the garbage sprites and the jumping/physics problems the original is known for, makes jumping feel like
other action games of its kind, adds a battery save, steadies the music when the game is busy, and brings in a
revised English script.

**Current release: v0.8b** — [`patch/Strider Repolished v0.8b.ips`](patch/)

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

## What changes

### Graphics
- **No more garbage sprites.** The game builds the next frame's sprites in the same page the video interrupt
  uploads, and its logic often runs longer than a frame, so half-built sprite tables were shown. Finished tables
  are now handed off safely (with a copy in cartridge RAM when needed); when no finished picture exists the previous
  one is repeated.
- The video interrupt no longer clobbers two zero-page bytes used by the interrupted code.
- **No digits on freshly spawned enemies.** Each level now loads its enemies' graphics over the ship's text font
  before it starts (while the screen is still black), so a new enemy never shows letters and numbers for its
  first frames. The pre-level black screen is 0.4–0.8 s longer. This also fixes an original bug where the level's
  first enemy set was meant to be loaded at the start but the request was overwritten a frame later.
  Not covered: the "KEY / FILE ACQUIRED" pick-up message, which reloads the font mid-level.

### Physics
- Running into a wall no longer makes Strider jitter back and forth by 4 pixels.
- Bumping a wall mid-jump only stops sideways movement; he no longer hovers while the jump counter runs out.
- Frames where movement is skipped no longer eat a step of the jump table; the hand-off from the jump table to the
  fall no longer drops him 12 px in one frame.
- Health/energy capsules dropped by enemies no longer bob up and down by a pixel while lying on the floor.

### Jump feel
- **Variable jump height:** releasing A while rising ends the rise (1 frame of A ≈ 8 px, 16+ frames = the full
  63 px jump as before). Triangle jumps and launcher tiles keep their fixed arc.
- **A wall no longer ends a jump.** It only blocks sideways movement, so jumping at a ledge while holding towards
  it works.
- **Triangle jump** can be done during a jump, with a more lenient window: A may come up to 4 frames before he
  turns round, and any time after while the wall is still in reach. A has to be pressed again; holding it does
  nothing.
- **Jump buffering:** A pressed up to 4 frames before landing makes him jump on landing.
- **Ceilings:** hitting a ceiling keeps the original's "glued to the ceiling" frames (some jumps depend on them),
  without the original's head-bobbing. Releasing A while glued shortens the glue.

### Saving
- The ship menu's **PASS/WORD** option is now **SAVE/GAME**: it writes the game to battery RAM, shows the password
  as before, and then returns to the ship instead of the title screen, so you can keep playing.
- The title screen's **PASSWORD** option is now **CONTINUE**: with a save it goes straight to the ship's menu; without
  one (or with a damaged one) it opens the password screen, so written passwords still work.
- A save is exactly what a password holds, so a loaded game is the same as one continued by password.

### Sound and speed
- **Steady music:** the music is driven from the video interrupt every frame (60 Hz) instead of once per game frame,
  so it no longer stutters when the game is busy. Sound effects work as before.
- **Slowdown instead of hitches:** when the game falls behind, every finished picture is shown, so busy scenes slow
  down slightly instead of stopping and jumping.
- Several hot loops (controller reads, hiding unused sprites, bank switching) are a few cycles shorter to pay for
  the sprite hand-off.

### Title and story screens
- New boot sequence: the "STRIDERS:" text is typed by the game's typewriter, slowly enough to run until the logo
  arrives; the title logo then drops from the top and stops in the middle, then the attract mode plays as before.
  Any button skips to the title screen.
- The closing animation of the attract mode (Strider sheathing his sword, with its sound effect) plays again.
- On the title menu, moving the cursor is silent and the confirm sound plays when an option is chosen.
- After saving, a button press ends the "NEXT EPISODE!" screen and the following story screen (also while they are
  still being typed).

### Revised English script
- 44 messages revised, based on the *Strider Script Revision* fan project: 33 dialogue/monitor messages, all 11
  story screens, and the status-screen item TRICK → CYPHR. Typos fixed on the way: HYRIU → HIRYU,
  STRENGHT → STRENGTH, a double space. The messages are repacked into the space that held them.

### Not changed
- The basic jump arc (fast rise, long float at the top), the fall speed, slope momentum.
- Enemy and gameplay timing: nothing is delayed, hidden or frozen to hide graphics problems.

## Known issues / not yet tested
- No full playthrough has been done yet; bosses and the ending are untested.
- Not yet tested on Mesen, FCEUX, MiSTer or real hardware/flash carts (whether each keeps the `.sav` file).
- Two text lines reach the last visible column and may be cut on a CRT.

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

## Disclaimer
Strider is © Capcom. This is an unofficial fan patch, not affiliated with or endorsed by Capcom or Nintendo.
This repository contains no ROM images or extracted game assets: only patch source code and an IPS patch to apply to your own copy.
