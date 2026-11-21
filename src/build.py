"""Strider Repolished: build the patched Strider (USA) ROM from the original + assembly patches.

usage: python src/build.py "Strider (USA).nes" [--retime] [--glue] [--preload] [--out file]
                           [--only sprites,physics,...] [--skip feel,...] [--tiles]

Strider Repolished v0.8b = --retime --glue --preload.
Each patch is (name, bank, asm-source). '.org' addresses are CPU addresses inside that bank
(bank 15 is the fixed bank at $C000-$FFFF, all others are mapped at $8000-$BFFF).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asm6502 import assemble

SRC = 'Strider (USA).nes'                    # set from the command line
OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build')
OUT = os.path.join(OUTDIR, 'Strider Repolished.nes')
# MMC1, SNROM class with a battery (256K PRG, 8K CHR-RAM, 8K battery RAM), the original cartridge type plus battery


PATCHES = []
def patch(name, bank, src):
    PATCHES.append((name, bank, src))

# =====================================================================================
# 1. Garbage sprites: never upload a half-built sprite table
#
#    The game builds next frame's sprites straight into the page the NMI uploads
#    ($0700), and its logic often takes longer than one video frame, so the NMI used to
#    upload whatever happened to be there.  Now:
#      - at the end of a logic frame the table is marked READY and the scroll position
#        that belongs to it is noted;
#      - if the game has to wait for vblank, the NMI uploads $0700 directly;
#      - if the frame overran, the game carries on; $0700 stays intact until the first
#        sprite-build call of the next frame, and only if vblank has not come by then
#        is the finished table copied to cartridge RAM ($6000) and shown from there;
#      - when nothing complete is available the NMI leaves the PPU's sprites alone and
#        re-sends the old scroll: the previous picture is repeated.
#    Needs the 8K of PRG-RAM at $6000 that MMC1 boards such as SNROM carry.  If it is
#    missing, STATE never reads back as one of the values below and the NMI behaves
#    exactly like the original.
# =====================================================================================
COMMON = r'''
SNAPBUF = $6000      ; copy of a completed sprite table (256 bytes)
STATE   = $6100      ; hand-off state between main thread and NMI
DSX     = $6101      ; scroll X of the picture currently on screen
DSY     = $6102
PSX     = $6103      ; scroll X belonging to the completed frame
PSY     = $6104
PNT     = $6105      ; name table bit belonging to the completed frame
ST_READY = $A5       ; $0700 holds a complete frame
ST_BUILD = $B1       ; $0700 is being rebuilt and nothing newer is waiting
ST_SNAP  = $5A       ; SNAPBUF holds a complete frame that has not been shown yet
; --- tiles that are still being streamed into CHR-RAM (see section 5) ---
HIDE    = $6106      ; bit 7: sprites that use a tile flagged in HID are hidden
MODE    = $6107      ; what ts_walk does: $80 hide+claim, $C0 hide only, $00 claim only
WTMP    = $6108
WEND    = $6109
WDIF    = $610A
WY      = $610B
WX      = $610E
W07     = $610C
W08     = $610D
HID     = $6200      ; per sprite tile: $80 = new contents not completely loaded yet
OWN     = $6300      ; per sprite tile: which source tile it holds (or is about to)
; --- music from the NMI, steady slowdown (section 12) ---
CURB    = $16        ; bank last selected through $C12D (the A it was called with)
OWED    = $17        ; 1: the NMI had to put a music tick off
MUS     = $DBF3      ; NMI music tick (section 12)
MUS0    = $BED0      ; ... its bank 0 part
'''
# (Assembled first: the fixed-bank code below jumps into it.  Optional: --tiles)
# The tail of bank 5 ($BEBC-$BFDF) is zero padding behind a stray piece of an Intel-HEX
# listing; nothing reads it.  It holds the bookkeeping for section 5.
patch('tiles', 5, COMMON + r'''
.org $BEBC
ts_boot:
    JSR ts_clr
    LDA #ST_BUILD
    STA STATE
    JMP $C52D
ts_clr:                  ; nothing is hidden
    LDA #$00
    TAX
tc_1:
    STA HID,X
    INX
    BNE tc_1
    STA HIDE
    RTS
ts_ptr:                  ; ($07) = script number $EF
    LDA $EF
    ASL A
    TAY
    LDA $E16A,Y
    STA $07
    LDA $E16B,Y
    STA $08
    RTS

; A tile-stream script is about to start ($EF = its number).
; Returns C set when sprites are being hidden for it: the caller then lets one frame pass
; before the first chunk goes out, so that a picture without those sprites is on screen
; (or queued) before any of their tiles change.
ts_start:
    JSR ts_ptr
    STA $ED              ; (replaced code) script pointer
    LDA $07
    STA $EC
    LDX #$80
    LDA $EF
    CMP $E6
    BEQ ts_2             ; an enemy set: flagged when it was asked for (ts_request)
    BIT HIDE
    BPL ts_1
    JSR ts_clr           ; a hiding stream or request was overridden by this one
ts_1:
    LDX #$00
ts_2:
    LDA #$00             ; (replaced code)
    STA $EF
    STA $EE
    STX MODE
    CPX MODE
    BNE ts_3             ; no cartridge RAM: nothing to keep track of
    JSR ts_walk
ts_3:
    LDA HIDE             ; (without RAM this reads $61)
    ASL A                ; C = something is hidden now
    RTS

; Enemy code asks for a tile set (was: STA $E6 / STA $EF at $EAC8; $EF is already set).
; Flag the tiles now, so that the enemy is already left out of the picture built in this
; very frame.  X, Y and $07/$08 belong to the caller.  Ends in the caller's bank.
ts_request:
    LDA $EF
    STA $E6
    STY WY
    CPY WY
    BNE tr_out           ; no cartridge RAM
    STX WX
    BIT HIDE
    BPL tr_1
    JSR ts_clr           ; an earlier request or stream is overridden
tr_1:
    LDA $07
    STA W07
    LDA $08
    STA W08
    JSR ts_ptr
    LDA #$C0             ; flag, but claim nothing yet
    STA MODE
    JSR ts_walk
    LDA W07
    STA $07
    LDA W08
    STA $08
    LDX WX
    LDY WY
tr_out:
    LDA $5E              ; back to the caller's bank
    JMP $C12D

; The script has reached its end: every tile it loads is in place.
ts_end:
    BIT HIDE
    BPL te_1
    JSR ts_clr
te_1:
    LDA #$00             ; (replaced code)
    STA $ED
    RTS

; Walk the script at ($07): for every sprite tile it is going to load, note which source
; tile will be there (OWN).  Tiles that already hold exactly that are left alone - the game
; reloads sets that are still in place all the time.  Where the contents really change,
; HID gets MODE: bit 7 set (hide until the stream is over) for an enemy set, $00 otherwise.
; OWN is only written when the stream really starts (MODE bit 6 clear).
ts_walk:
    LDY #$00
tw_entry:
    INY
    LDA ($07),Y          ; destination, high byte
    CMP #$10
    BCS tw_skip          ; background pattern table, or $FF = end of the script
    ASL A
    ASL A
    ASL A
    ASL A
    STA WTMP
    DEY
    LDA ($07),Y          ; destination, low byte
    LSR A
    LSR A
    LSR A
    LSR A
    ORA WTMP
    TAX                  ; X = first tile
    STX WEND
    INY
    INY
    LDA ($07),Y          ; source, low byte
    LSR A
    LSR A
    LSR A
    LSR A
    STA WTMP
    INY
    LDA ($07),Y          ; source, high byte (bits 7-6 select the bank)
    PHA
    ASL A
    ASL A
    ASL A
    ASL A
    ORA WTMP             ; bits 4-11 of the source address = source tile number
    STA WTMP
    PLA
    AND #$C0
    CLC
    ADC WTMP             ; ...told apart by bank
    SEC
    SBC WEND
    STA WDIF             ; (source tile id) - (destination tile), constant for the entry
    INY
    LDA ($07),Y          ; number of 32-byte pieces
    ASL A                ; = number of tiles (at most 140: carry is clear)
    ADC WEND
    STA WEND             ; first tile behind the entry (0 = up to $FF)
tw_tile:
    TXA
    CLC
    ADC WDIF
    CMP OWN,X
    BEQ tw_same
    BIT MODE
    BVS tw_flag          ; only asked for: the request can still be overridden
    STA OWN,X
tw_flag:
    LDA MODE
    STA HID,X
    STA HIDE
tw_same:
    INX
    CPX WEND
    BNE tw_tile
    INY
    BNE tw_entry         ; always
tw_skip:
    CMP #$FF
    BEQ tw_rts
    INY
    INY
    INY
    INY
    BNE tw_entry         ; always
tw_rts:
    RTS
''')

patch('sprites', 15, COMMON + r'''
; ---------------- NMI handler (rewritten) ----------------
.org $C0ED
nmi:
    PHA
    TXA
    PHA
    TYA
    PHA
    LDA $03              ; the NMI path uses $03/$04 as scratch; the interrupted
    PHA                  ; main thread may be using them too, so preserve them
    LDA $04
    PHA
    JSR $C517            ; NMI off
    LDA #$00
    STA $2001            ; rendering off while we touch VRAM
    LDA $51
    BEQ nmi_a
    LDX $4E
    LDY $4D
    JSR $C210            ; queued name table column / text
nmi_a:
    LDA $04CE
    BEQ nmi_b
    BPL nmi_c
nmi_b:
    JSR $C8E0            ; queued palette / tile updates
nmi_c:
    LDX #$07
    JMP nmi_sel
nmi_dma:
    LDA #$00
    STA $2003
    STX $4014
    LDA #ST_BUILD        ; whatever was just shown is now "old": anything the main
    STA STATE            ; thread builds from here on must be handed over again
    RTS
; (64 bytes available up to $C12C; the IRQ vector still points at the old SEI/RTI)

.org $E7EA
nmi_sel:
    LDA STATE
    CMP #ST_BUILD
    BEQ nmi_keep         ; sprite table is being rebuilt: repeat the last picture
    CMP #ST_SNAP
    BEQ nmi_snap
    CMP #ST_READY
    BEQ nmi_show         ; live table is complete (X = $07)
    JMP nmi_live         ; no PRG-RAM on this cartridge: behave like the original
nmi_snap:
    LDX #>SNAPBUF
nmi_show:
    LDA PSX              ; scroll that belongs to the frame being shown
    STA DSX
    LDA PSY
    STA DSY
    LDA $45
    AND #$FE
    ORA PNT
    STA $45
    JSR nmi_dma
nmi_keep:
    LDA $2002            ; reset the address latch, then (re)send the scroll that
    LDA DSX              ; belongs to the sprites that are on screen
    STA $2005
    LDA DSY
    STA $2005
    JMP nmi_fin

.org $E6CA
nmi_live:
    JSR nmi_dma          ; X = $07
    JSR $C2F6            ; scroll from the live variables (original routine)
nmi_fin:
    INC $4B
    LDA $46
    STA $2001
@m  JSR $C523            ; NMI on
@M  JSR MUS              ; music tick (section 12), then NMI on
    PLA
    STA $04
    PLA
    STA $03
    PLA
    TAY
    PLA
    TAX
    PLA
nmi_iret:
    SEI
    RTI

; ---------------- sprite builders: copy the finished table if it is still unseen ----
; $EFD4 ("select the sprite data bank") is the first thing both sprite builders call.
lazy_snap:
    LDA STATE
    CMP #ST_READY
    BNE lazy_done
    JMP lazy_go
lazy_done:
    JMP efd4_body
.org $E905
lazy_go:
    LDA #$FB             ; bank 3 (the routine selects its own bank right after)
    JSR $C12D
    JSR $BEE1
    JMP efd4_body
.org $EFD4
    JMP lazy_snap
efd4_body:               ; the original routine, a little tighter (tail call)
    LDX $F2
    LDA $04A0
    AND #$04
    BEQ efd4_a
    LDX #$05
    TXA
    .db $2C              ; BIT abs: skip the next instruction
efd4_a:
    LDA #$FA
    JMP $C04E

; ---------------- main loop: end of a logic frame ----------------
.org $C15E
    JSR frame_done
.org $C0E7
    JSR boot_init
; On SNROM-type boards bit 4 of MMC1 CHR register 0 switches the cartridge RAM off, and
; the game never writes that register, so its power-on value would decide whether the RAM
; (and with it this fix) works.  Clear it once at boot: five serial writes of a 0 bit.
; (With 8K of CHR-RAM the register has no other function.  X is 0 on entry and on exit.)
.org $FFBF
boot_init:
    LDA #$00
    LDX #$05
boot_1:
    STA $A000
    DEX
    BNE boot_1
    JMP boot_2
.org $FFAC
boot_2:
@N  LDA #ST_BUILD
@N  STA STATE
@N  JMP $C52D
@T  LDA #$FD             ; bank 5: clear the tile flags, STATE = BUILD, then on to $C52D
@T  JSR $C12D
@T  JMP ts_boot
frame_done:
    JSR $C523            ; (replaced instruction) NMI on
    LDA #$FB             ; bank 3: note the scroll of the finished frame, mark it READY
    JSR $C12D            ; (the main loop selects the sound bank right after the wait)
    JMP $BF80
''')

patch('sprites', 3, COMMON + r'''
; Copy the finished sprite table to SNAPBUF (four sprites per pass).
.org $BEE1
; STATE stays READY during the copy ($0700 is only read here), so an NMI that comes
; in the middle still uploads the finished table from $0700 and sets BUILD.  (It used
; to be BUILD for the whole copy: under steady load the copy straddled vblank frame
; after frame and the picture stood still for up to 19 frames while the game ran.)
; Without cartridge RAM lazy_snap never gets here (STATE does not read back as READY).
snapshot:
    LDX #$00
snap_loop:
    LDA $0700,X
    STA SNAPBUF+0,X
    CMP #$F0             ; hidden sprite: Y is all that matters
    BCS snap_n0
    LDA $0701,X
    STA SNAPBUF+1,X
    LDA $0702,X
    STA SNAPBUF+2,X
    LDA $0703,X
    STA SNAPBUF+3,X
snap_n0:
    LDA $0704,X
    STA SNAPBUF+4,X
    CMP #$F0             ; hidden sprite: Y is all that matters
    BCS snap_n4
    LDA $0705,X
    STA SNAPBUF+5,X
    LDA $0706,X
    STA SNAPBUF+6,X
    LDA $0707,X
    STA SNAPBUF+7,X
snap_n4:
    LDA $0708,X
    STA SNAPBUF+8,X
    CMP #$F0             ; hidden sprite: Y is all that matters
    BCS snap_n8
    LDA $0709,X
    STA SNAPBUF+9,X
    LDA $070A,X
    STA SNAPBUF+10,X
    LDA $070B,X
    STA SNAPBUF+11,X
snap_n8:
    LDA $070C,X
    STA SNAPBUF+12,X
    CMP #$F0             ; hidden sprite: Y is all that matters
    BCS snap_n12
    LDA $070D,X
    STA SNAPBUF+13,X
    LDA $070E,X
    STA SNAPBUF+14,X
    LDA $070F,X
    STA SNAPBUF+15,X
snap_n12:
    TXA
    CLC
    ADC #$10
    TAX
    BNE snap_loop
    LDA STATE
    CMP #ST_READY        ; shown from $0700 in the meantime? then the copy is not needed
    BNE snap_rts         ; (an NMI between CMP and STA only repeats that picture once)
    LDA #ST_SNAP
    STA STATE
snap_rts:
    RTS

; End of a logic frame: remember the scroll position that goes with the table in
; $0700 and flag it as complete.
.org $BF80
frame_ready:
@M  LDA STATE            ; section 12: the previous frame was finished and copied but has not been on
@M  CMP #ST_SNAP         ; screen yet - wait for the NMI that shows it instead of dropping it (the NMI
@M  BEQ frame_ready      ; is on: frame_done turned it on; it sets BUILD after the upload)
    LDA #ST_BUILD        ; (an older copy that was never shown is dropped here)
    STA STATE
@T  BIT HIDE             ; (without cartridge RAM this reads $61: bit 7 clear)
@T  BMI fr_hide
fr_0:
    LDA $0546
    LSR A
    BCC fr_1
    LDA $A2
    LDX $A5
    LDY $A3
    BCS fr_2
fr_1:
    LDA $053B
    LDX $053E
    LDY $053C
fr_2:
    STA PSX
    STX PSY
    TYA
    AND #$01
    STA PNT
    LDA #ST_READY
    STA STATE
    RTS
@T  ; An enemy tile set is streaming in (section 5): hide every sprite whose tile does not
@T  ; hold its new contents yet.  Sprite slots 0-7 are the HUD.
@T  fr_hide:
@T  LDA $ED
@T  ORA $EF
@T  BEQ fr_0             ; no stream is running or waiting (any more)
@T  LDY #$20
@T  fh_1:
@T  LDX $0701,Y
@T  LDA HID,X
@T  BPL fh_2
@T  LDA #$F8
@T  STA $0700,Y
@T  fh_2:
@T  LDX $0705,Y
@T  LDA HID,X
@T  BPL fh_3
@T  LDA #$F8
@T  STA $0704,Y
@T  fh_3:
@T  TYA
@T  CLC
@T  ADC #$08
@T  TAY
@T  BNE fh_1
@T  BEQ fr_0
''')


# =====================================================================================
# 2. Make room in the fixed bank
#    Five copies of the same "look up animation pointer in bank 2" routine live at
#    $E871/$E891/$E8D1/$E8F1/$E911.  Their bodies move to the unused tail of bank 2
#    (the bank they switch to anyway); the entry points stay where they were.
# =====================================================================================
def _anim_body(n, lo, hi):
    return f"""
anim{n}:
    ASL A
    BCC anim{n}_lo
    TAY
    LDA ${hi:04X},Y
    PHA
    LDA ${hi+1:04X},Y
    JMP $E92E
anim{n}_lo:
    TAY
    LDA ${lo:04X},Y
    PHA
    LDA ${lo+1:04X},Y
    JMP $E92E
"""
ANIM = [(0xE871, 0x8602, 0x8702), (0xE891, 0x8802, 0x8902), (0xE8D1, 0x8202, 0x8302),
        (0xE8F1, 0x8402, 0x8502), (0xE911, 0x8002, 0x8102)]
_b2 = ".org $BF24\n" + "".join(_anim_body(i, lo, hi) for i, (_, lo, hi) in enumerate(ANIM))
patch('room', 2, _b2)
_b2sym = assemble(_b2)[1]
_stubs = "".join(f"""
.org ${e:04X}
    JSR to_bank2
    JMP ${_b2sym['anim%d' % i]:04X}
""" for i, (e, _, _) in enumerate(ANIM))
patch('room', 15, _stubs + r'''
.org $E877
to_bank2:
    PHA
    LDA #$FA
    JSR $C04E            ; switch to bank 2
    PLA
    RTS
''')

# =====================================================================================
# 3. Physics
# =====================================================================================
patch('physics', 1, r'''
; --- P1: running into a wall.  The "eject 4 pixels" logic is meant for standing inside
;     a wall, but it also fired every time the wall-stop logic zeroed X velocity, so
;     Strider bounced back and forth.  Do not eject while the player is pushing into
;     the wall he is facing.
.org $8821
    JSR $E897            ; Z clear -> skip ejection
    BNE $884E
    NOP
    NOP
    NOP

;  --- P2: the head target hits something during a jump while heel and shin are free.
;     The original erased X and Y velocity every frame but left the jump frame counter
;     running, so Strider froze/hovered in mid-air until the table ran out, whether it
;     was a ceiling above him or just a wall in front of his head.  Tell the two apart:
;     wall -> only stop moving sideways.  Ceiling -> the rise ends, but the jump does
;     not: the counter is moved to where the table starts coming down ($17, unless it is
;     already further), so he comes off the ceiling the way he comes off the top of a
;     normal jump (1 px/frame at first) instead of dropping at the 4 px/frame fall
;     speed.  While his head is still inside the ceiling he moves down 2 px/frame: the
;     game's own head check ($9401) zeroes the table's Y velocity there, which is what
;     used to make him hover.
.org $8F6C
    JMP $E8DE

;  --- --glue (2026-11-21): the ceiling branch of P2 (p2c) comes here.  The original erased all velocities and
;     let the counter run, so he stuck under the ceiling while the jump table still pushed him up hard (level jumps
;     rely on it), but the +1.5 ascent compensation ($8FF4) moved him 1.5 px down and the table put him back the
;     next frame: he bobbed, drifting down until the table's push fell to -2 px (counter $1F-$21 for a plain jump).
;     Now: while the table entry for this frame is -3 or stronger (same index as $991E-$9924), Y velocity = -1.5,
;     which the +1.5 cancels: he stays still with his head at the ceiling.  After that, +1.5 px/frame until his head
;     is out (the game's head check would otherwise hold him until the table runs out), then the table as usual.
;     $B7B7-$B7D6: orphan PPU string command, $9B32-$9B43: unreferenced subroutine (free-space study).
@G.org $B7B7
@Gp2g:
@G  LDY $0528
@G  LDA $0527
@G  LSR A
@G  CLC
@G  ADC $99A1,Y
@G  TAY
@G  LDA $99AC,Y          ; this frame's table entry (negative = up)
@G  ADC #$01             ; C = 0 here: -2 or stronger stays negative
@G  BPL p2g_off
@G  LDA #$FE             ; -1.5: held at the ceiling
@G  .db $2C              ; (BIT abs: skips the next LDA)
@Gp2g_off:
@G  LDA #$01             ; +1.5: off the ceiling
@G  STA $0515
@G  JMP p2g2
@G.org $9B32
@Gp2g2:
@G  LDA #$80
@G  STA $0514
@G  JMP $8F7D            ; X velocity 0, then on to $8F95 as the original's $8F87 does

; --- P3 (triangle jump accepts A being held) is gone: see section 7, F2.

; --- P4: frames on which the movement step is skipped (pending scroll updates) still
;     consumed one step of the jump table.  Give the step back.
.org $8BB8
    JMP $E8F7
;     Same thing for the other skip path, where the whole movement routine is bypassed
;     but the jump code (which steps the counter) is still called.
.org $83BD
    JSR $E928

; --- P5: the frame the jump table ends, table velocity (+8) and the freshly started
;     fall velocity (+4.09) were both applied: a 12 pixel drop in one frame.
.org $90F2
    JSR $E917
    NOP
    NOP
''')
patch('physics', 15, r'''
.org $E897
p1_eject_ok:
    LDA $050E            ; d-pad (left+right filtered)
    AND $051B            ; facing direction uses the same bits
    AND #$03
    BNE p1_rts           ; pushing forward: no ejection
    LDA $0512            ; (replaced code) only eject when standing still
    ORA $0513
p1_rts:
    RTS

.org $E8DE
p2a:
    LDA $0527
    BEQ p2_all           ; jump already cancelled by the heel/shin paths: as before
    LDA $050B
    PHA
    SEC
    SBC $054B            ; top of the head, at Strider's own X (no forward offset)
    JMP p2b
p2_all:
    JMP $8F87            ; Erase_All_Velocities
.org $FFCD
p2b:
    STA $050B
    JSR $C904            ; raw environment lookup at (X, Y)
    TAY
    PLA
    STA $050B
    TYA
    AND #$03
    JMP p2c
.org $E87F
p2c:
    BEQ p2_wall
@G  JMP p2g             ; --glue: glued under the ceiling until the rise is over, as the original (bank 1)
@g  LDA #$17             ; ceiling: on to the falling part of the jump table
@g  JSR jmin
@g  LDA #$02             ; out of the ceiling
@g  STA $0515
p2_wall:
    JMP $8F7D            ; Erase_Lateral_Velocities only; the jump goes on
.org $E8A8               ; (leftover of the lookup that was at $E891)
jmin:                    ; jump counter = min(counter, A)
    CMP $0527
    BCS jmin_r
    STA $0527
jmin_r:
    RTS

.org $E8F7
p4_skip:
    LDA $0527
    BEQ p4_a
    INC $0527            ; undo this frame's decrement
p4_a:
    LDA #$00             ; (replaced code)
    STA $0517
    RTS

.org $E928
p4_skip2:
    JSR $96FD            ; (replaced instruction) jump processing
    JMP p4_skip

.org $E917
p5_fall_start:
    LDA #$04             ; (replaced code) initial fall velocity
    STA $054E
    LDA $0515
    BMI p5_rts           ; still moving up: add the fall velocity as before
    CMP #$04
    BCC p5_rts
    PLA                  ; already falling at >= 4 px/frame from the jump table:
    PLA                  ; do not stack the fall velocity on top of it this frame
p5_rts:
    RTS
''')

# =====================================================================================
# 4. Give a little CPU time back (the hand-off above costs some every frame)
# =====================================================================================
patch('speed', 15, r'''
; Bank switch: "TAY / STA $5E" now sits directly in front of the switch routine, so the
; common entry ($C04E) no longer hops through $C18A.  (The three bytes used to be the
; tail of the old NMI handler; the IRQ vector, which pointed at its SEI/RTI, moves to
; the new handler's.)
.org $C12A
    TAY
    STA $5E
.org $C04E
    JMP $C12A
.org $C18A
    JMP $C12A
.org $FFFE
    .dw nmi_iret
; Hide-unused-sprites loop: the end of the ring ($04CA) is always 0, and INY already
; sets Z when Y wraps to 0, so the compare is not needed.
.org $C824
    LDY $F4
    LDA #$F8
hide_loop:
    STA $0700,Y
    INY
    INY
    INY
    INY
    BNE hide_loop
    BEQ $C834            ; (the original tail "LDA #0 / STA $FD / RTS" stays where it is)

; Controller code, repacked ($C368 is the only entry point used from outside).  The
; shorter read loops leave room for three new bytes: a history of "A was newly pressed"
; per logic frame (bit 7 = this frame, bit 6 = the frame before, ...) in the unused
; zero-page bytes $1C (pad 1) and $1D (pad 2).  Section 7 (F4) reads it.
.org $C368
    LDA $47
    STA $49
    LDA $48
    STA $4A
    JSR pad_read
    LDX #$00
    JSR pad_new
    INX
pad_new:
    LDY #$00
    LDA $49,X
    EOR #$FF
    AND $47,X
    STA $54,X
    STA $5A,X
    ASL A                ; C = A newly pressed
    ROR $1C,X
    RTS
pad_read:
    JSR $C332
    JSR pad_a0
    INX
    JSR pad_a0
    JSR $C332
    JSR pad_b0
    INX
    JMP pad_b0
pad_a0:
    LDY #$08
pad_a:
    LDA $4016,X
    LSR A
    ROL $07
    DEY
    BNE pad_a
    LDA $07
    STA $47,X
pad_rts:
    RTS
pad_b0:
    LDY #$08
pad_b:
    LDA $4016,X
    LSR A
    LSR A
    ROL $07
    DEY
    BNE pad_b
    LDA $07
    TAY
    BEQ pad_rts
    STA $47,X
    RTS
''')

# =====================================================================================
# 5. Enemies drawn before their tiles have arrived
#
#    Enemy graphics live in CHR-RAM and are streamed in by small scripts (player at
#    $DA8F, request in $EF, one 32/64-byte chunk per frame).  Enemy code asks for its
#    set and is drawn from the same frame on, so for 8-20 frames it appeared built from
#    whatever those tiles held before: letters, or the previous enemy type.
#    Now, while such a script runs, sprites whose tile is still waiting for its new
#    contents are not drawn (fr_hide, at the end of every logic frame).  The tiles
#    are flagged the moment enemy code asks for the set (ts_request).  A table in
#    cartridge RAM remembers what each sprite tile holds, so the many reloads of a set
#    that is already in place hide nothing.  Only sets requested through the enemy
#    entry point ($EAB1) are treated this way; scripts started by player, level and
#    cutscene code behave as before.  Without cartridge RAM nothing changes.
# =====================================================================================
patch('tiles', 15, COMMON + r'''
.org $DAA0               ; a new script starts (was: look up its pointer, clear $EF and $EE)
    JSR to_bank5
    JSR ts_start
    BCS $DA8E            ; sprites are hidden for it: first chunk next frame (RTS)
    JMP $DAB2
.org $DAAD
to_bank5:
    LDA #$FD
    JMP $C12D
.org $DAC7               ; end of the script (was: LDA #$00 / STA $ED / RTS)
    JMP ts_end_far
.org $E828
ts_end_far:
    JSR to_bank5
    JMP ts_end
.org $EAC8               ; enemy code asks for a tile set (was: STA $E6 / STA $EF)
    JSR ts_req_far
    NOP
.org $E6F4
ts_req_far:
    STA $EF
    JSR to_bank5
    JMP ts_request
''')

# =====================================================================================
# 6. Capsules dropped by enemies bounce one pixel up and down on the ground
#
#    The capsule loop (bank E $AEB9) calls the shared ground routine $B277 with a fake
#    X velocity of 1, so that on solid ground it is put one pixel above the tile row
#    (Y = $xF).  The collision lookup at that height says "air", so gravity pulls it
#    down again: after 2-3 frames it reaches $x0, is drawn there once, and the next
#    frame's ground check lifts it back.  An original bug (same in the unpatched ROM).
#    Fix: same calls, other order - move first, then check the ground.  A capsule that
#    crossed into the tile row is put back before it is drawn, so it is always shown at
#    its resting height (and no longer shown sunk into the floor on the landing frame).
#    Same bytes, same cycle count; the shared routines are untouched.  Capsules from
#    containers (bank 3 $B717) rest on the tile row itself and never bounced.
# =====================================================================================
patch('items', 14, r'''
.org $AEBE               ; was: LDA #1 / STA $0213,X / JSR $B277 / LDA #0 / STA $0213,X / JSR $B30C
    JSR $B30C            ; add velocity to position (X velocity is 0 here)
    LDA #$01
    STA $0213,X          ; fake X velocity: "walker" -> rests one pixel above the tiles
    JSR $B277            ; ground check: gravity in the air, snap + stop on the ground
    LDA #$00
    STA $0213,X
''')

# =====================================================================================
# 7. Jump feel
#
#    F1  A wall no longer ends a jump.  The original zeroed the jump counter as soon as
#        the toe probe touched a wall (after the first 6 frames, or at once when he had
#        run-up momentum), so jumping at a ledge while holding towards it dropped him
#        36 px up, and a jump next to a wall only worked without a direction held.  Now
#        the wall only blocks the sideways movement (which the game already does every
#        frame at $8F7D); the jump runs its course and he moves over the edge once his
#        feet are above it.
#    F2  Triangle jump during a jump.  The wall cancel above was also what made the
#        triangle jump available quickly: the game only looked for it once the jump
#        counter was 0.  The check now runs during a jump too.  Conditions as before
#        (in the air, a wall within 32 px behind him, facing away from the direction of
#        the jump before).  It takes a new press of A, but not on one exact frame as in
#        the original: a press up to 4 frames before the conditions are met counts
#        (same history byte as F4), so "A, then turn" works as well as "turn, then A".
#        Holding A does nothing: P3 (A held is enough, the video's Game Genie code) was
#        dropped again - it caused unwanted triangle jumps.
#    F3  Jump height.  Letting go of A while still rising skips the rest of the ascent
#        (jump counter -> $21, the top of the table's arc).  One frame of A gives about
#        8 px, holding it the full jump as before.  Not for triangle jumps or the
#        launcher tiles ($0561 bit 0).
#    F4  A pressed up to 4 frames before landing is no longer lost: the ground jump
#        looks at the last five frames of new A presses ($1C, kept by the controller
#        code in section 4) instead of this frame's only.
#
#    Room: the block $97D3-$98E8 (triangle check + ground jump start) is rewritten in
#    place, a little tighter; F3 lives in the first 16 bytes of the jump velocity table
#    ($99AC-$99BB), which no jump type can index (offsets are $10, $28, $28, $48), and in
#    two leftovers of the relocated animation lookups in the fixed bank.
# =====================================================================================
FEEL = r'''
JBUF   = $1C         ; history of new A presses, one bit per logic frame (bit 7 = now)
vj2     = $E8A8      ; jmin (section 3): jump counter = min(counter, A)
tri_dir = $E8D7
'''
patch('feel', 1, FEEL + r'''
; --- F1
.org $93C0
    NOP                  ; was: STA $0527 (A = 0)
    NOP
    NOP

; --- F2 (+ F3 hook, F4)
.org $97D3
    LDA $050B
    CMP #$20
    BCS tri
    LDA #$00             ; too close to the top of the screen: the jump ends
    STA $0527
tri:
    LDA $0500
    AND #$02
    ORA $0545
    BNE tri_early
    LDA $054C
    AND #$03
    BNE tri_early        ; on the ground
    LDA $037B
    ORA $0538
    BNE tri_fail
    LDA $056D            ; direction of the jump before
    EOR $051B
    AND #$03
    BEQ tri_fail         ; has not turned
    LDA JBUF             ; a new press of A, this frame or one of the 4 before
    AND #$F8
    BEQ tri_fail
    LDA $051B
    AND #$03
    BEQ tri_fail
    LSR A                ; C = facing right
    LDA $0508
    PHA
    LDA #$20
    BCC tri_probe
    LDA #$DF             ; + carry = -$20
tri_probe:
    ADC $0508
    STA $0508
    JSR $C8E9            ; what is 32 px behind him?
    AND #$03
    TAY
    PLA
    STA $0508
    CMP #$E8
    BCS tri_fail
    CPY #$03
    BNE tri_fail
    JSR tri_dir          ; $056D = facing
    LDA #$01
    ORA $0561
    STA $0561
    LDA #$00
    STA JBUF             ; the press is used up
    LDY #$03
    STY $0528
    JMP jtab
tri_fail:
    LDA $0527
    BNE jcont
    LDA $055E
    AND #$03
    BNE jstart
jrts:
    RTS
tri_early:
    LDA $0527
    BEQ jstart
jcont:
    JSR vj               ; F3
    JMP $98E9            ; next step of the running jump
    NOP                  ; (padding: the code below has to end at $98E3)
    NOP

; ground jump (original code; A press now taken from the history, two compares shorter)
jstart:
    LDA $050D
    CMP #$0C
    BCS js_1
    AND #$03
    BNE jrts
js_1:
    LDA $04D9
    BNE jrts
    LDA JBUF             ; F4 (was: LDA $5A / BPL)
    AND #$F8
    BEQ jrts
    LDA $050B
    CMP #$30
    BCC jrts
    LDA $050E
    AND #$04
    ORA $04D0
    BNE jrts
    LDY $0545
    DEY
    BNE js_3
    LDA $0554
    ROR A
    LDA #$08
    BCC js_2
    LDA #$F8
js_2:
    CLC
    ADC $0508
    STA $0508
js_wait:
    LDA $EF
    ORA $ED
    BEQ js_2b
    JSR $C023
    JSR js_wait
js_2b:
    LDA #$03
    STA $EF
js_3:
    LDA #$2C
    JSR $C037
    LDY $0545
    DEY
    BNE js_4
    LDA #$02
    STA $EF
js_4:
    LDA #$00
    STA $0545
    STA $054E
    STA JBUF             ; the press is used up
    LDA $050E
    STA $056D
    AND #$0F
    CMP #$05
    BEQ $994B            ; (an RTS)
    CMP #$06
    BEQ $994B
    LDA $050E
    STA $055B
    JSR $994C
js_end:                  ; must be $98E3: falls through into the original code there
jtab = $98E3             ; LDA $99A0,Y / STA $0527, then $98E9

; --- F3
.org $99AC
vj:
    BIT $47
    BMI vj_r             ; A held
    LDA $0561
    LSR A
    BCS vj_r             ; triangle jump / launcher: fixed arc
    LDA #$21
    JMP vj2
vj_r:
    RTS
''')
patch('feel', 15, FEEL + r'''
.org $E8D7               ; (leftover of the lookup that was at $E8D1)
    LDA $051B
    STA $056D
    RTS
''')

# =====================================================================================
# 8. Save to battery RAM instead of writing a password down  (patch name 'save')
#
#    The game's password is its whole saved state: 12 characters made from $048B-$0490.
#    - Hub menu, third option (was PASS/WORD, now SAVE/GAME; bank 1 $B084): as before it
#      shows the password in the lower left window and, after a button, the "next
#      story" text - and the 12 characters are also written to cartridge RAM.  The text
#      used to end the session (back to the title); now the hub is loaded again and its
#      menu opens, so the game goes on.
#    - Title screen, second option (was PASSWORD, now CONTINUE; hub entry, bank 1 $AB95):
#      if cartridge RAM holds a record, its 12 characters are put where the password
#      entry screen leaves the typed ones and the game's own "password complete" code
#      ($B25E) decodes and checks them.  Without a record (or with a damaged one) the
#      password entry screen opens as before, so passwords still work.
#    Record at $7F00: 12 characters, checksum (sum EOR $5A), signature $53.
#    Code in the unused tail of bank 5, reached through 8 bytes in the fixed bank;
#    which of the two it is follows from $04D6 bit 0 (set by the title screen, what the
#    hub itself tests at $AB09 / $AB8F, and never set once the menu is reached).
# =====================================================================================
SAVE = r"""
LG5     = $BEBC          ; section 10 (boot sequence) entry in bank 5
SV_REC  = $7F00
SV_SUM  = $7F0C
SV_SIG  = $7F0D
"""
patch('save', 5, SAVE + r"""
.org $BF00
sv_main:
@I  LDA $04D0            ; attract ($04D0) or ending ($04DF) running: the boot sequence's helper (section 10)
@I  ORA $04DF
@I  BMI LG5
    LDA $0580            ; bit 5: the "next story" text is on screen ($B0CE) - it is over, back to the menu
    AND #$20
    BEQ sv_m1
    LDA #$00
    STA $0580            ; text mode off
    STA $04A0            ; menu closed, its task idle
    STA $04A1
    JSR $C2E8            ; all sprites off screen (the text's cursor sprite would stay for half a second)
    JSR $C88C            ; the game's own "start the level in $CB again": player task idle ($0500/01),
    JMP sv_exit          ; $F0 and $A0 = 0 (the level engine draws the screen again, then bank 1 runs
                         ; $810D = level entry; with $0500 = 0 the hub opens its menu, $833A), objects cleared
sv_m1:
    LDA $04D6
    LSR A
    BCS sv_load
    ; ---- save: $0202-$020D hold the password characters ($A904 has just made them)
    LDX #$0B
sv_s1:
    LDA $0202,X
    STA SV_REC,X
    DEX
    BPL sv_s1
    JSR sv_sum
    STA SV_SUM
    LDA #$53
    STA SV_SIG
    LDA $048B            ; the game goes on now: undo what $A904 left in the state - its check nibble in
    AND #$0F             ; the top of $048B (the level number: indexes tables, e.g. $B108) and the check
    STA $048B            ; byte in $0490, which is the timer that locks Strider's controls ($9132, $EB38)
    LDA #$00
    STA $0490
    LDA #$1E             ; what the replaced JSR $C084 did: picture on
    STA $2001
    STA $46
sv_exit:
    LDA #$F9             ; back to bank 1; the RTS of $C12D returns to the caller there
    JMP $C12D
    ; ---- load
sv_load:
    LDA #$00             ; (what $AB95-$ABA1 did)
    STA $04D6
    LDA $048C
    ORA #$80
    STA $048C
    LDY #$01             ; Y = 1: nothing to load
    JSR sv_sum
    CMP SV_SUM
    BNE sv_exit
    LDA SV_SIG
    CMP #$53
    BNE sv_exit
    LDX #$0B
sv_l1:
    LDA SV_REC,X
    STA $0202,X
    DEX
    BPL sv_l1
    AND #$0F             ; the key the entry screen takes from the first character ($B243)
    STA $04BF
    DEY                  ; Y = 0: record loaded
    BEQ sv_exit
sv_sum:                  ; A = (sum of the 12 record bytes, carries dropped) EOR $5A; X = $FF
    LDX #$0B
    LDA #$00
sv_c1:
    CLC
    ADC SV_REC,X
    DEX
    BPL sv_c1
    EOR #$5A
    RTS
""")
patch('save', 15, SAVE + r"""
.org $E6F4
sv_far:
    LDA #$FD             ; bank 5
    JSR $C12D
    JMP sv_main
""")
patch('save', 1, SAVE + r"""
.org $AB95               ; title option 2 chosen (was: clear $04D6, $048C |= $80, JMP $B154)
    JSR sv_far
    DEY
    BEQ $ABA2            ; no record: the password entry screen
    JMP $B25E            ; record in $0202-$020D: the game's own "12 characters entered"
    NOP
    NOP
    NOP
    NOP
.org $B092               ; hub menu option 3, password on screen (was: JSR $C084, picture on)
    JSR sv_far
.org $B0E8               ; end of the "next story" text (was: $40 |= $20 / RTS = back to the title screen)
@k  JSR sv_far           ; out of the text mode, hub to be loaded again   ('@k': only without section 11,
@k  RTS                  ; end of the menu task for this frame              which rewrites $B09A-$B0ED)
.org $B6E8               ; menu label PASS / WORD
    .db $53,$41,$56,$45,$FB,$40,$47,$41,$4D,$45      ; SAVE / GAME
""")
patch('save', 7, r"""
.org $8772               ; title screen: PASSWORD
    .db $43,$4F,$4E,$54,$49,$4E,$55,$45              ; CONTINUE
""")

# =====================================================================================
# 10. Boot sequence (2026-11-20): the game starts with the "STRIDERS-" text typed by the game's
#     own typewriter; at the tick where the original showed that text, the title logo drops from the
#     top of the screen and stops in the middle; from the Sheena banner on, the attract plays as
#     before (same music ticks).  Any button (A, B, Select, Start) ends it at any point; it ends on the
#     title screen (logo + menu), which is silent now.  The title screen left alone replays the sequence.
#
#     Original flow: title routine $C564/$C573 (CHR, title picture, music track 0, then 768 frames of
#     title) -> $C62F: level $0C = attract.  Bank 1 $80AA types message 1, waits for the end of the
#     page, then 120 frames ($80EF), then $8106 starts the scenes.  Attract frame counter $04D1/$04D2
#     (main loop $C775) ends the attract at $1200 frames, then $C799 -> title.
#
#     Now: the title routine still runs (music starts at tick 0), but with LG_BOOT set ($C564 reset path
#     and the title's own time-out) $C600 jumps straight to the attract.  The text appears ~37 ticks after
#     boot.  Bank 1 $80EF calls the helper once per logic frame (through the save patch's bank-5
#     trampoline sv_far): until LG_TL it waits; at LG_TL it switches the picture off, loads the title's
#     tiles $80-$FF (bank D $B000 -> PPU $1800, as $C8C2 does), clears both name tables ($C2AA), sets
#     horizontal mirroring, draws the logo with the title screen's own stream (bank 7 $8699, data $87E8:
#     rows 4-17 of name table A + attributes) and lets it fall: Y scroll $053E and the vertical name
#     table bit ($45 bit 1) put the logo above the screen; gravity 1/16 px/frame^2 (half the speed of the first version, 2026-11-21) brings it down to
#     y 64-175 (centred) in ~76 frames.  At LG_TE (the original's $8106 tick) it blanks the picture,
#     restores vertical mirroring and scroll, sets the attract counter to the original's value there
#     (637) and returns to $8106.  $C799 (button or end) calls the same restore.
#     Code: bank 5 $BEBC (34 bytes) + routines copied to cartridge RAM $7F80-$7FC3 (they call bank 7 /
#     bank D / fixed code); per-frame step in bank 9's unused tail $BF40-$BFDF, entered by mapping bank 9
#     in from bank 5 $BF97 (execution goes on at $BF9C in bank 9).
#     RAM (cartridge): LG_BOOT $7FF0, state $7FF1-$7FF6.
# =====================================================================================
INTRO = r"""
LG_BOOT = $7FF0          ; $80: the boot sequence runs (title routine goes to the attract); 0: title screen
LG_PH   = $7FF1          ; 0 waiting, 1 logo on screen
LG_Q    = $7FF2          ; fall: distance left (px) + 32 ... 0 = resting
LG_QL   = $7FF3
LG_V    = $7FF4          ; speed, 8.8 px/frame
LG_VL   = $7FF5
LG_T    = $7FF6
ST_RAM  = $7F80          ; set-up routine in cartridge RAM (47 bytes)
RST_RAM = $7FAF          ; restore routine in cartridge RAM (21 bytes)
LG_TL   = 804            ; attract frame counter when the logo comes (= music tick 805, the original text)
LG_TE   = 1300           ; ... when the scenes start: the original's $8106 is at music tick 1301 ...
LG_CE   = 532            ; ... with attract counter 532.  (Until 2026-11-21: 1405/637, measured on a build whose revised
                         ;  boot text is 37 characters longer - the attract then timed out before Hiryu sheathes his
                         ;  sword, bank 1 $BA9C, sound $3C, at counter 4546)
"""
from asm6502 import assemble as _asm
_LG_SRC = r"""
.org $7F80
st_ram:
    JSR $C517            ; NMI off
    JSR $C2AA            ; picture off; both name tables blank (text mode: tile $A0), attributes 0
    LDX #$B0             ; title tiles $80-$FF: bank D $B000 -> PPU $1800 (what $C8C2 does)
    LDY #$18
    LDA #$20
    JSR $DA47
    LDA #$0F             ; MMC1 control: horizontal mirroring (PRG/CHR modes as before)
@m  JSR $C146
@M  JSR $C148            ; (section 12 moved the MMC1 control routine 2 bytes up)
    LDA #$FF             ; bank 7: the title screen's logo stream -> name table A rows 4-17 + attributes
    JSR $C12D
    LDX #$87
    LDY #$E8
    JSR $8699
    JSR $C2E8            ; no sprites
    LDA #$1E
    STA $46              ; picture on at the next NMI
    JSR $C523            ; NMI on
    LDA #$01             ; back to bank 9 (caller)
    JMP $C12D
rst_ram:
    LDA #$00
    STA $2001            ; picture off now
    STA $053E
    LDA #$10             ; (what the attract sets next)
    STA $46
    LDA $45
    AND #$FD             ; name table $2000 again
    STA $45
@m  JMP $C144            ; vertical mirroring
@M  JMP $C146            ; vertical mirroring (section 12: routine moved)
"""
def _lgr(music):
    """the RAM routines, assembled with or without section 12 ('@M' / '@m' lines)"""
    keep, drop = ('@M', '@m') if music else ('@m', '@M')
    src = chr(10).join(l.replace(keep, '  ', 1) for l in _LG_SRC.splitlines() if not l.lstrip().startswith(drop))
    r = _asm(src)[0][0x7F80]
    assert len(r) == 68, len(r)
    return ','.join('$%02X' % v for v in r)
patch('intro', 5, INTRO + r"""
.org $BEBC
lg5:                     ; from sv_main (bank 5) during the attract / ending
    LDX #$02
    BIT $04DF
    BMI lg5_x            ; ending: X = 2, bank 1 runs the original ending wait
    LDY #67
lg5_c:
    LDA lg_ram,Y         ; (re)copy the RAM routines
    STA ST_RAM,Y
    DEY
    BPL lg5_c
    BIT LG_BOOT
    BPL lg5_r            ; called from $C799: back to the title screen
    JMP lg_b5
lg5_r:
    JSR RST_RAM
lg5_x:
    LDA #$F9             ; bank 1; the RTS of $C12D returns to the caller
    JMP $C12D
.org $BF97
lg_b5:
    LDA #$01             ; bank 9: execution goes on at $BF9C there (lg9)
    JSR $C12D
lg_ram:
@m  .db """ + _lgr(False) + r"""
@M  .db """ + _lgr(True) + r"""
""")
patch('intro', 9, INTRO + r"""
.org $BF40
lg9_done:
    LDA #<LG_CE
    STA $04D1
    LDA #>LG_CE
    STA $04D2
    JSR RST_RAM
    LDX #$01             ; X = 1: on to $8106
    JMP lg9_x
lg9_fall:                ; X = 0
    LDA LG_VL
    CLC
@r  ADC #$10             ; gravity 1/16 px/frame^2 (was $40: half the speed)
@R  ADC #$04             ; --retime: 1/64 px/frame^2, half the speed again (fall ~150 frames)
    STA LG_VL
    BCC lf1
    INC LG_V
lf1:
    LDA LG_QL
    SEC
    SBC LG_VL
    STA LG_QL
    LDA LG_Q
    SBC LG_V
    BCS lf2
    TXA                  ; landed
lf2:
    STA LG_Q
    LDY #$00
    SEC
    SBC #32              ; Y scroll = Q - 32: below 0 -> name table $2800 (B), Y + 240
    BCS lf3
    ADC #240
    LDY #$02
lf3:
    STA $053E
    STY LG_T
    LDA $45
    AND #$FD
    ORA LG_T
    STA $45              ; (one store: the NMI never sees a half-made value)
    JMP lg9_x
.org $BF9C
lg9:
    LDX #$00
    LDA $04D1
    CMP #<LG_TL
    LDA $04D2
    SBC #>LG_TL
    BCS lg9_go
    STX LG_PH            ; waiting (the first calls come while the text is on screen)
lg9_x:
    LDA #$F9             ; bank 1; X = 0 wait a frame, 1 done
    JMP $C12D
lg9_go:
    LDA $04D1
    CMP #<LG_TE
    LDA $04D2
    SBC #>LG_TE
    BCS lg9_done
    LDA LG_PH
    BNE lg9_fall
    JSR ST_RAM           ; logo screen
    LDX #$00
    STX LG_QL
    STX LG_V
    STX LG_VL
    INC LG_PH
    LDA #178             ; logo bottom just above the screen
    STA LG_Q
    JMP lg9_fall
""")
patch('intro', 1, INTRO + r"""
.org $80AA               ; attract / ending text page; same code, 4 bytes shorter, then the new wait
    LDA #$20
    STA $0580
    JSR $C040
    JSR $C046
    JSR $C03D
    JSR $C087
    LDA #$1E
    STA $46
    LDA #$00
    STA $053C
    LDY #$01
    BIT $04DF
    BPL lt1
    STA $04A0            ; (A = 0)
    LDA #$21
    STA $DE
    LDA $0552
    ORA #$08
    STA $0552
    LDY #$0C
lt1:
    STY $FF
    JSR $C023
    JSR $C046
lt2:
    JSR $C023
    LDA $FF
    BNE lt2
lt3:
    JSR sv_far           ; X: 0 wait, 1 scenes, 2 ending
    DEX
    BEQ lt_go
    BPL lt_end
    JSR $C023
    JMP lt3
lt_end:                  ; the original ending wait
    LDA #$0E
    JSR $C037
    JSR $C006
    LDA #$96
    JSR $C008
lt_go:                   ; = $8106
""")
patch('intro', 15, INTRO + r"""
.org $C564               ; reset path into the title routine (was LDA #$80 / STA $40)
    JSR lg_set
    NOP
.org $C5E2               ; title music (was LDA #$00 / JSR $C037)
    JSR lg_mus
    NOP
    NOP
.org $C600               ; (was JSR $C523)
    JSR lg_chk
.org $C62A               ; title time-out (was DEC $04CE)
    JSR lg_dec
.org $C775               ; attract frame counter; any button ends the attract (not the ending)
    LDA $04D0
    BPL $C7B4
    LDA #$78
    BIT $04DF
    BMI lc_e
    LDA $54              ; newly pressed: A $80, B $40, Select $20, Start $10
    AND #$F0
    BNE $C799
    LDA #$12
lc_e:
    INC $04D1
    BNE $C7B4
    INC $04D2
    CMP $04D2            ; limit - count
    BEQ lc_t
    BCS $C7B4
lc_t:                    ; (the JSR $C2AA / JSR $C2E8 that were here: the title routine does both
    NOP                  ;  before its first frame)
.org $C79B               ; back to the title screen (button or end): was STA $04D0 / $04D1 / $04D2
    STA LG_BOOT          ; title screen, not the boot sequence
    JSR sv_far           ; restore picture / mirroring (A = 0 on return)
    STA $04D0
.org $E828
lg_set:
    LDA #$80
    STA $40
    STA LG_BOOT
    RTS
.org $FFE7
lg_mus:                  ; boot sequence: track 0; title screen: $FF (silence)
    LDA LG_BOOT
    ASL A
    SBC #$00
    JMP $C037
.org $FCEF
lg_chk:
    JSR $C523
    BIT LG_BOOT
    BPL lg_c1
    PLA
    PLA
    LDA #$0C             ; level $0C = attract, as the time-out did
    JMP $C631
lg_c1:
    RTS
.org $C8D0
lg_dec:
    DEC $04CE
    BPL lg_d1
    PLA
    PLA
    LDA #$80             ; title left alone: the boot sequence again (music from the start)
    STA LG_BOOT
    JMP $C573
lg_d1:
    RTS
""")

# =====================================================================================
# 10b. --retime (2026-11-21; optional): the boot text is typed slower, so that it ends shortly
#     before the logo comes (was: typed in frames 52-535, then ~285 frames of standing text; now ~52-797),
#     the logo falls at half the speed again (bank 9 gravity $10 -> $04, '@R' line above) and the first
#     line reads "STRIDERS:" (now in revised.json, so every build has it since 2026-11-21).
#     The typewriter waits 3 frames per character (bank 7 $843F LDA #$03 / JSR $C008, shared by every
#     typewriter); now JSR tw: the attract/ending/story typewriter ($0580 bit 5) with message 1 (the boot
#     text; the ending is $0C) waits 4 or 5 frames by the character's PPU column ($4D & 7, 5 of 8 -> 5),
#     4.625 on average; everything else 3 as before.  $C008 is entered by JMP, so it takes the return
#     address of JSR tw ($8441) and the task resumes at the NOPs.  tw sits in bank 7's stale tail
#     (level-map leftovers, free-space study; checked never read).
#     (The sword-sheath timing fix and the title menu's confirm sound began here on 2026-11-21 and are in every build
#     with section 10 now: LG_TE/LG_CE in INTRO, and the 'intro' bank 15 patch at $C63F / $DC83 below.)
# =====================================================================================
patch('retime', 7, r"""
.org $843F
    JSR tw
    NOP
    NOP
.org $BF80
tw:
    LDA $0580
    AND #$20
    BEQ tw3              ; hub / dialogue typewriter
    LDA $FF
    CMP #$01
    BNE tw3              ; not the boot text
    LDA $4D
    AND #$07
    TAX
    LDA tw_t,X
    JMP $C008
tw3:
    LDA #$03
    JMP $C008
tw_t:
    .db 5,4,5,5,4,5,4,5
""")
patch('intro', 15, r"""
.org $C63F               ; title menu: Select moves the cursor silently (was BNE $C648: sound $2B, then the move)
    BNE $C64D
    JMP tc_go            ; Start: the sound, then the original confirm ($C6AF)
.org $DC83               ; (unused table entries, free-space study: verified, never read)
tc_go:
    LDA #$2B             ; the cursor sound, now on confirm
    JSR $C037
    LDA #56              ; let it play out (56 frames) before the screen goes black ($C6EF silences everything)
    JSR $C008            ; title task: wait, resume below
    LDA #$00
    STA $54
    JMP $C6AF
""")

# =====================================================================================
# 11. "NEXT EPISODE!" screens can be skipped (2026-11-21): a button (A, B, Select, Start) while
#     "NEXT EPISODE!" is on ends that screen; another press ends the story screen ("... DON'T MISS IT!").
#     Patch name 'nskip'; it needs the save patch (it ends in sv_far).  Nothing changes while no button is
#     pressed, and nothing runs outside these screens: gameplay frames are cycle-for-cycle as without it.
#     (A first version hooked the bank 7 text task, which runs every frame: +16 cycles on every frame.)
#     The screens are the save option's tail, bank 1 $B09A-$B0E7, run by the hub menu task (record $04A0:
#     +1 wait count, +2/3 resume address - 1, +4 incremented by the scheduler on every resume, $C4AF).
#     Originally: font $1D + 30 frames, clear, font $2F + 30 frames, "NEXT EPISODE!" (message $7B) and 2 x 60
#     frames, clear, font $1D + 30 frames (black), text mode + story message, typing loop ($B456), 2 x 240.
#     Now the waits on the two text screens are 1-frame yields through the game's own $B45E (+4 = A, yield;
#     on resume A = +4 + 1 and Z when it wraps to 0), so +4 counts the frames: $88 -> 120 frames; while the
#     story is still being typed ($FF != 0) the count is held at $1E, then $1E -> 225 and 0 -> 256 frames, which
#     with the frame that sees $FF = 0 is the original typing loop + 480.  Each frame `h` looks at the new
#     presses ($54 >= $10: A, B, Select or Start); a press sets $FF = 0 (typewriter off: the text task tests
#     $FF before it resumes typing) and returns at once with Z = 1, so the loop ends in that frame - and on the
#     story screen the next loop sees the same press and ends too.  The black screen in between is a plain
#     30-frame wait: a press there does nothing.
#     Room: $B09A-$B0BA compacted (A = 0 when the $B452 loop ends, so the LDA #$00 goes; font + 30 frames is a
#     small helper), $B0E8-$B0ED (the save patch's JSR sv_far / RTS, now JMP sv_far inside this code), and
#     bank 1 $BFE7-$BFF9: 13 zero bytes and a stale copy of the internal-header bytes 48 04 00 00 08 AC between
#     the reset stub ($BFE0-$BFE6) and the vectors - never read or executed (63 coverage scenarios, static
#     scans of all banks; the same bytes are in every bank).  Design and prototype: free-space study 2026-11-21.
# =====================================================================================
patch('nskip', 1, r"""
.org $B09A               ; after the button that follows the password (A = 0 here)
    STA $46              ; picture off at the next NMI (was LDA #$00 / STA $46)
    JSR nk_1d            ; font $1D, 30 frames
    JSR $C03D            ; name tables cleared
    LDA #$2F
    JSR nk_fn            ; font $2F, 30 frames
    LDA #$21
    STA $DE
    LDA #$7B
    STA $FF              ; "NEXT EPISODE!"
    LDA #$08
    STA $46
    JSR $C046
    LDA #$88             ; 120 frames
nk_l1:
    JSR nk_h
    BNE nk_l1
    JSR $C03D
    JSR nk_1d            ; black, font $1D, 30 frames
    JSR nk_st            ; story text started; first frame of the loop below
nk_l2:
    JSR nk_hs            ; while typing, then 225 frames
    BNE nk_l2
nk_l3:
    JSR nk_h             ; 256 frames (A = 0 from the loop above)
    BNE nk_l3
    JMP sv_far           ; out of text mode, hub loaded again (was JSR sv_far / RTS at $B0E8)
nk_hs:
    LDX $FF              ; still typing: hold the count
    BEQ nk_h
    LDA #$1E
nk_h:
    LDX $54              ; new presses: A, B, Select, Start
    CPX #$10
    BCS nk_pr
    JMP $B45E            ; +4 = A, wait one frame (resume: A = +4 + 1, Z at 0)
nk_pr:
    LDA #$00
    STA $FF              ; typewriter off; Z = 1: this screen ends now
    RTS
nk_1d:
    LDA #$1D
nk_fn:
    STA $EF              ; tile stream
    JMP $C049            ; 30 frames
.org $BFE7
nk_st:
    LDA #$20
    STA $0580            ; text mode
    LDA $048B
    AND #$0F
    CLC
    ADC #$02
    STA $FF              ; story message 2 + level
    JMP nk_hs
""")

# =====================================================================================
# 12. Music from the NMI; a slow frame is a slowdown, not a stall (patch 'music', 2026-11-21)
#     What the game did: the sound driver (bank 0 $8000) was called by the main loop ($C16C-$C173), once per logic
#     frame, so every logic frame that overran a video frame dropped a music tick.  And after an overrun the
#     loop does not wait for vblank (it catches up), so two frames could be finished between two NMIs; section 1
#     then dropped the older one (frame_ready: "an older copy that was never shown is dropped here") - the
#     picture stood for a frame, then jumped.
#     Now:
#       - the NMI ticks the driver every video frame, after the picture is switched back on (mus, below);
#       - frame_ready waits while the previous finished frame (copied to SNAPBUF) has not been shown yet, so no
#         finished frame is ever dropped.  The catch-up after an overrun stays: the game only falls behind when
#         it is really behind, a frame is never skipped, and a frame that fits runs exactly as before.
#         (Tried first: Mega Man's rule, wait for vblank after every frame.  Logic frames per 4,000 video frames
#         fell by 19% in fx1, 22% in level 3, 28% in level 7 - Strider's frames sit at 0.85-1.3 video frames.)
#     MMC1 safety: a bank switch is five serial writes into one shift register; the NMI's own switches must not
#     mix with a half-written value.
#       - $C12D notes the bank it selects (CURB) before its first write.  Every MMC1 write sequence of the game
#         sits in $C132-$C15A: the bank switch ($C12D-$C145) and the control register routine ($C146-$C15B).
#       - Interrupted inside the bank switch after 1-4 of its writes ($C135-$C142): the NMI resets the shift
#         register, plays, restores the bank in full (= the switch's target, CURB) and then writes the low bits of
#         that same value again, as many as the switch had done; its remaining writes complete the same value.
#         Nothing is put off and the main thread's registers are untouched.
#       - Interrupted inside the control register sequence ($C14B-$C15A, the boot sequence's mirroring changes
#         only), or in page $FF (boot_init writes MMC1 CHR register 0 with the NMI on; boot_2, frame_done), or in
#         $8000-$BFFF with bank 0 selected (the driver itself, or a sound request $C4DA -> $8003; no driver code
#         calls into the fixed bank): the tick is put off (OWED) and the next NMI runs two.
#       - OWED is not cleared at power-on (no room left in the boot code); a stray non-zero value costs one
#         extra tick of the still-silent driver at the first NMI.
#       - The driver's RAM ($20-$35, $0400-$047D) is written by nothing else except the RAM clear $C3C6, which
#         always runs with the NMI off (traced: fx1, level 7).
#     The control routine moved 2 bytes up: $C144 -> $C146 (LDA #$0E entry), $C146 -> $C148 (A = value); the
#     power-on MMC1 reset (INC $FFE1, was $C15A) moved to $C3C1 (a leftover of the speed patch's repack).
#     Room: zero page $16-$17 (never touched: traced fx1, levels 1/2/4/8/10/11); fixed bank $DBF3-$DC3A and
#     $DC63-$DC7A, bank 0 $BED0-$BFDF (unused table entries / stale sfx copy; free-space study, verified; never
#     read in the same runs).
#     The NMI still writes $2000 (NMI on, with the name table bit of the frame it set up) before vblank ends:
#     mus does that first (a first version did it after the tick, inside the picture: chk_sprites counted 2,207
#     frames with the wrong scroll in fx1).
# =====================================================================================
patch('music', 15, COMMON + r"""
.org $C12D
bsw:                     ; bank switch (A = bank - 8): unchanged apart from noting the bank first
    STA CURB
    CLC
    ADC #$08
    STA $FFE1
bsw_1:                   ; from here to mctl_end the MMC1 shift register can hold a partial value
    LSR A
    STA $FFE1
    LSR A
    STA $FFE1
    LSR A
    STA $FFE1
    LSR A
    STA $FFE1
    RTS
mctl:                    ; was $C144: MMC1 control = $0E (vertical mirroring)
    LDA #$0E
mctl_a:                  ; was $C146: MMC1 control = A
    STA $8002
    LSR A
    STA $8002
    LSR A
    STA $8002
    LSR A
    STA $8002
    LSR A
    STA $8002
mctl_end:
    RTS

.org $C0B5               ; power-on: MMC1 reset, then control register
    JSR mrst
    JSR mctl
.org $C3C1
mrst:                    ; was $C15A
    INC $FFE1
    RTS

; Main loop: the sound driver call ($C16C-$C173: bank 0, JSR $8000) goes; the NMI does it now.
.org $C16C
    JMP $C174
ml_end:

; NMI, after the picture is switched back on (called instead of JSR $C523).
; Stack here: +1/+2 return, +3 $04, +4 $03, +5 Y, +6 X, +7 A, +8 P, +9/+10 interrupted PC.
.org MUS
mus:
    JSR $C523            ; NMI on - first: it writes $2000, whose name table bit belongs to the frame that is
                         ; about to start (the tick below runs into the picture; the next NMI is a frame away)
    TSX
    LDY #$00             ; Y = writes a half-done bank switch had made (0: none)
    LDA $010A,X          ; high byte of the interrupted PC
    CMP #$C1
    BNE mus_1
    LDA $0109,X          ; low byte
    CMP #$4B             ; $C14B-$C15A: control register sequence
    BCC mus_b
    CMP #$5B
    BCC mus_owe
    BCS mus_go
mus_b:
    SBC #$30             ; (C = 0) A = PCL - $31: $C135/$C136 -> 1 write done ... $C141/$C142 -> 4
    BCC mus_go           ; before the first write
    LSR A
    LSR A
    CMP #$05
    BCS mus_go           ; the switch is complete ($C145) or not ours
    TAY
    LDA #$80
    STA $8000            ; MMC1: drop the partial value (control bits 2-3 are set already)
    BNE mus_go           ; (always)
mus_1:
    CMP #$FF
    BEQ mus_owe          ; page $FF: boot_init (MMC1 CHR register 0), boot_2, frame_done
mus_go:
    TYA
    PHA
    LDA CURB
    PHA
    LDA #$F8             ; bank 0: sound driver
    JSR $C12D
    JSR MUS0
    PLA
    JSR $C12D            ; back to the interrupted code's bank (its switch's target, complete)
    PLA
    BNE mus_p            ; a switch was half done: give the shift register its bits back
    RTS
mus_end1:
.org $DC63
mus_p:
    TAY
    LDA CURB
    CLC
    ADC #$08
mus_p1:
    STA $FFE1
    LSR A
    DEY
    BNE mus_p1
    RTS
mus_owe:
    LDA #$01
    STA OWED
    RTS
mus_end:
""")
patch('music', 0, COMMON + r"""
; Section 12, bank 0: the tick itself, unless the driver (or a sound request) is what the NMI interrupted.
; Stack here: +1/+2 return, +3 CURB, +4 writes done, +5/+6 return of mus, +7..+11 NMI pushes, +12 P, +13/+14 PC.
.org MUS0
mus0:
    TSX
    LDA $0103,X
    CMP #$F8
    BNE m0_go
    LDA $010E,X
    CMP #$C0
    BCS m0_go
    LDA #$01             ; bank 0 code was running: tick at the next NMI
    STA OWED
    RTS
m0_go:
    JSR $8000
    LDA OWED
    BEQ m0_r
    LDA #$00
    STA OWED
    JSR $8000            ; the tick that was put off
m0_r:
    RTS
m0_end:
""")

# =====================================================================================
# 13. Enemy tiles loaded at level entry (patch 'preload', 2026-11-21; only with --preload)
#     What the game does (read from the code, measured on both ROMs: the original shows the same glyphs about as
#     often): the ship streams its text font into sprite tiles $80-$FF (script $1C; $3C = $B0-$CF), and nothing
#     replaces it before a level starts.  An enemy is drawn from the frame it asks for its set ($EAB1), 4 tiles
#     arrive per frame, so until then its sprites show font tiles: digits and letters.
#     The level entry (bank 1 $814B, a task: waits are inline yields $C023 that drop the stack and registers)
#     already asks for one set per level at $8186 (table $8226: $32 $0B $0A $0B $14 - $1F $0F $1F $1E $32 $32 for
#     levels 0-4, 6-11), which is exactly the first set each level's enemies ask for - but nothing waits for it, and
#     Strider's own request (02) replaces $EF a frame later, so it is never loaded (traced: Kazakh entry streams 01,
#     then 02, never $32).
#     Now, after Strider's set (script 01) is in and before the original goes on at $8175: the level's list below is
#     streamed set by set, each one waited for, with the background still off (PPU mask $10 there).  $E6 (the
#     enemy set the game thinks is loaded) is the loop's position in the list, since a yield keeps no registers;
#     at the end it is cleared, so each enemy's first request streams its set once more - the same data, already
#     on screen, unless the original's own $8186 request (it does stream when $0545 is set: wait at $81B0) wrote
#     over part of it.  The lists cover every font tile ($1C $A0-$EF, $3C $B0-$CF) that any set of the level uses
#     (static placement scan + the first requests of replays), so a set that is not loaded
#     yet shows another enemy of the level, as the original does elsewhere, never a digit or a letter.  Same
#     condition as the original's own request ($0552 bit 5 / $04D0 bit 7 set: nothing); levels without a list
#     (5, 6, 12, 13) run exactly as before.  In-level dialogues (bank 7 $8052 loads $3C) return through this entry,
#     so they are covered too (traced, level 9).  Not covered: the item event $F821 (KEY / FILE acquired: script
#     $1C over $80-$FF, 90 frames frozen) does not leave through the entry.
#     Cost: 25-48 frames more black screen per level entry (also after a dialogue; a lost life: not traced).
#     Room (bank 1, free-space study, verified dead): code $A4C2-$A50A (old 6-digit sprite score routine), level
#     offsets $90A6-$90C5 (unreferenced subroutine head), lists $92FA-$9319 (unused data table).
# =====================================================================================
# Smallest covers of the font tiles ($1C $A0-$EF, $3C) that the level's sets use, each with the level's $8226 set;
# the first set the level's enemies ask for goes last (its tiles intact).  Identical lists are shared, and a list
# may be the tail of another (10 = tail of 11).
PL_LISTS = {0: [0x07, 0x32, 0x39], 1: [0x30, 0x32, 0x0B], 2: [0x06, 0x32, 0x0A], 3: [0x05, 0x0F, 0x0B], 4: [0x11, 0x1E, 0x14],
            7: [0x0F, 0x1E], 8: [0x0F, 0x32, 0x1F], 9: [0x0F, 0x1E], 10: [0x1F, 0x32], 11: [0x0F, 0x1F, 0x32]}
def _pl_src():
    data, offs = [], {}
    for lv in sorted(PL_LISTS, key=lambda l: -len(PL_LISTS[l])):
        want = PL_LISTS[lv] + [0]
        for i in range(len(data) - len(want) + 1):       # already there (whole list or a tail of another one)?
            if data[i:i + len(want)] == want: offs[lv] = i; break
        else: offs[lv] = len(data); data += want
    assert len(data) <= 32, f'preload: lists take {len(data)} bytes, $92FA-$9319 has 32'
    off = [offs.get(lv, offs[0] + len(PL_LISTS[0])) for lv in range(14)]   # no list: level 0's terminator
    return (".org $90A6\npl_off:\n    .db " + ",".join(f"${o:02X}" for o in off) +
            "\n.org $92FA\npl_list:\n    .db " + ",".join(f"${b:02X}" for b in data) + "\n")
patch('preload', 1, _pl_src() + r"""
.org $8175
    JMP pre              ; was LDA $0552
.org $A4C2
pre:
    LDA $0552            ; the original's condition for its level set request ($8175-$817D)
    ASL A
    ASL A
    ORA $04D0
    BMI pl_out
    LDY $CB
    LDX pl_off,Y
    LDA pl_list,X
    BEQ pl_out           ; no list for this level: nothing changes
    LDA #$00
    STA $E6              ; start of the list
pl_next:                 ; also the resume point after each finished stream
    LDY $CB
    LDX pl_off,Y
    LDA $E6
    BEQ pl_take
pl_find:                 ; the entry after $E6
    LDA pl_list,X
    BEQ pl_out           ; $E6 not in the list (someone else asked for a set): stop
    INX
    CMP $E6
    BNE pl_find
pl_take:
    LDA pl_list,X
    BEQ pl_done
    STA $EF              ; stream it
    STA $E6
pl_wait:
    JSR $C023
    LDA $ED
    ORA $EF
    BNE pl_wait
    BEQ pl_next
pl_done:
    LDA #$00             ; every set counts as not loaded: an enemy's first request streams its set again
    STA $E6              ; (the same data, unless the original's $8186 request has written over part of it)
pl_out:
    LDA $0552
    JMP $8178
pl_end:
""")

# in-place edits of original code: (bank, first, last)
INPLACE = [(15, 0xC0ED, 0xC12C), (15, 0xC15E, 0xC160), (15, 0xC0E7, 0xC0E9),
           (15, 0xE871, 0xE92D), (15, 0xEFD4, 0xEFE8), (15, 0xC04E, 0xC050), (15, 0xC18A, 0xC18F), (15, 0xC824, 0xC833), (15, 0xFFFE, 0xFFFF), (15, 0xC368, 0xC3C5), (15, 0xDAA0, 0xDAB1), (15, 0xDAC7, 0xDACB), (15, 0xEAC8, 0xEACB),                       # relocated animation lookups + helpers
           (1, 0x8821, 0x8828), (1, 0x8F6C, 0x8F6E), (1, 0x93C0, 0x93C2), (1, 0x97D3, 0x98E2),(1, 0x99AC, 0x99BB),(1, 0x8BB8, 0x8BBA), (1, 0x83BD, 0x83BF), (1, 0x90F2, 0x90F6),
           (14, 0xAEBE, 0xAECD),
           (1, 0xAB95, 0xABA1), (1, 0xB092, 0xB094), (1, 0xB0E8, 0xB0EE), (1, 0xB6E8, 0xB6F1), (7, 0x8772, 0x8779),
           (1, 0x80AA, 0x8105), (15, 0xC564, 0xC567), (15, 0xC5E2, 0xC5E6), (15, 0xC600, 0xC602), (15, 0xC62A, 0xC62C), (15, 0xC775, 0xC798), (15, 0xC79B, 0xC7A3),   # section 10
           (1, 0xB09A, 0xB0EE), (1, 0xBFE7, 0xBFF9),   # section 11 (overlaps the save entry: one or the other writes $B0E8-$B0ED)
           (15, 0xC12D, 0xC15D), (15, 0xC16C, 0xC173), (15, 0xC0B5, 0xC0BA),   # section 12 ($C3C1 is inside the speed patch's range)
           (1, 0x8175, 0x8177), (1, 0xA4C2, 0xA50A), (1, 0x90A6, 0x90C5), (1, 0x92FA, 0x9319),
           (1, 0xB7B7, 0xB7D6), (1, 0x9B32, 0x9B43),
           (7, 0x843F, 0x8443), (7, 0xBF80, 0xBFDF),
           (15, 0xC63F, 0xC643), (15, 0xDC83, 0xDC9A)]   # section 10 title menu: sound on confirm (free-space study: $DC83 verified unused)   # --retime (bank 7 tail: stale level-map leftovers)   # --glue (free-space study: orphan PPU string command, unreferenced subroutine)   # section 13 (dead code / unused data, free-space study)
FREE = {15: [(0xE6CA, 0xE6FF), (0xE7EA, 0xE82F), (0xFFAC, 0xFFDF), (0xC8D0, 0xC8DF), (0xFCEF, 0xFCFF), (0xFFE7, 0xFFEF), (0xDBF3, 0xDC3A), (0xDC63, 0xDC7A)], 0: [(0xBED0, 0xBFDF)], 3: [(0xBEE1, 0xBFDF)], 2: [(0xBF24, 0xBFDF)], 5: [(0xBEBC, 0xBFDF)], 9: [(0xBF40, 0xBFDF)]}
def build(only=None, out=OUT, verbose=True, tiles=False, skip=(), preload=False, glue=False, retime=False):
    rom = bytearray(open(SRC, 'rb').read())
    used = {}; gsym = {}
    for name, bank, src in PATCHES:
        if name == 'tiles':
            if not tiles: continue
        elif name == 'preload':
            if not preload or tiles: continue
            if only and name not in only: continue
        elif name == 'retime':
            if not retime: continue
        elif only and name not in only: continue
        if name in skip: continue
        # '@T' lines exist only in the --tiles variant, '@N' lines only without it
        keep, drop = ('@T', '@N') if tiles else ('@N', '@T')
        src = '\n'.join(l.replace(keep, '  ', 1) for l in src.splitlines() if not l.lstrip().startswith(drop))
        # '@I' lines exist only with section 10 (boot sequence); it needs the save patch's trampoline
        intro = 'intro' not in skip and 'save' not in skip and not tiles and (not only or ('intro' in only and 'save' in only))
        if name == 'intro' and not intro: continue
        src = '\n'.join(l.replace('@I', '  ', 1) for l in src.splitlines() if intro or not l.lstrip().startswith('@I'))
        # section 11 (skippable next-episode screens) needs the save patch; '@k' lines exist only without it
        nsk = 'nskip' not in skip and 'save' not in skip and not tiles and (not only or ('nskip' in only and 'save' in only))
        if name == 'nskip' and not nsk: continue
        src = '\n'.join(l.replace('@k', '  ', 1) for l in src.splitlines() if not nsk or not l.lstrip().startswith('@k'))
        # section 12 (music from the NMI, steady slowdown): '@M' lines only with it, '@m' lines only without it
        mus = 'music' not in skip and not tiles and (not only or 'music' in only)
        if name == 'music' and not mus: continue
        keep, drop = ('@M', '@m') if mus else ('@m', '@M')
        src = '\n'.join(l.replace(keep, '  ', 1) for l in src.splitlines() if not l.lstrip().startswith(drop))
        # --glue (2026-11-21): '@G' lines only with it, '@g' lines only without it (P2 ceiling branch)
        keep, drop = ('@G', '@g') if glue else ('@g', '@G')
        src = '\n'.join(l.replace(keep, '  ', 1) for l in src.splitlines() if not l.lstrip().startswith(drop))
        # --retime (2026-11-21): '@R' lines only with it, '@r' lines only without it (logo gravity)
        keep, drop = ('@R', '@r') if retime else ('@r', '@R')
        src = '\n'.join(l.replace(keep, '  ', 1) for l in src.splitlines() if not l.lstrip().startswith(drop))
        chunks, sym = assemble(src, gsym)
        gsym.update({k: v for k, v in sym.items() if v is not None})
        if name == 'music' and bank == 15:
            assert sym['bsw_1'] == 0xC135 and sym['mctl'] == 0xC146 and sym['mctl_a'] == 0xC148 and sym['mctl_end'] == 0xC15B, 'music: MMC1 routines moved'
            assert sym['mus'] == 0xDBF3 and sym['mus_end1'] <= 0xDC3B and sym['mus_end'] <= 0xDC7B, 'music: code does not fit'
        if name == 'music' and bank == 0:
            assert sym['mus0'] == 0xBED0 and sym['m0_end'] <= 0xBFE0, 'music: bank 0 code does not fit'
        if name == 'preload':
            assert sym['pl_end'] <= 0xA50B, f"preload: code ends at ${sym['pl_end']:04X}, room up to $A50A"
        if name == 'feel' and bank == 1:
            assert sym['js_end'] == 0x98E3, f"feel: ground jump code ends at ${sym['js_end']:04X}, must be $98E3"
        for addr, data in chunks.items():
            base = 0xC000 if bank == 15 else 0x8000
            assert base <= addr and addr + len(data) <= base + 0x4000, (name, hex(addr))
            ok = any(b == bank and a0 <= addr and addr + len(data) - 1 <= a1 for (b, a0, a1) in INPLACE) or                  any(a0 <= addr and addr + len(data) - 1 <= a1 for (a0, a1) in FREE.get(bank, []))
            assert ok, f'{name}: chunk bank {bank:X} ${addr:04X}-${addr+len(data)-1:04X} is outside the allowed regions'
            off = 16 + bank * 0x4000 + (addr - base)
            for i in range(len(data)):
                k = off + i
                assert k not in used, f'patch overlap at bank {bank:X} ${addr+i:04X} ({name} vs {used[k]})'
                used[k] = name
            rom[off:off + len(data)] = data
            if verbose: print(f'  {name:10s} bank {bank:X} ${addr:04X}-${addr+len(data)-1:04X} ({len(data)} bytes)')
    # 9. Revised English script (src/text_patch.py; needs src/revised.json, which is not part of this repository)
    if 'text' not in skip and (not only or 'text' in only):
        import text_patch
        if text_patch.available():
            rom = text_patch.apply(rom, verbose, src=SRC)
        else:
            print('  text      SKIPPED: src/revised.json not found (the revised script is not distributed here);'
                  ' the ROM keeps the original text and will not match the release patch')
    # NES 2.0 header: mapper 1, 256K PRG, 8K CHR-RAM, 8K PRG-RAM - battery-backed when the save patch is in
    # (SNROM with a battery: the board of The Legend of Zelda and Final Fantasy)
    battery = 'save' not in skip and (not only or 'save' in only)
    rom[7] = (rom[7] & 0xF0) | 0x08
    rom[8] = 0; rom[9] = 0; rom[10] = 0x70 if battery else 0x07; rom[11] = 0x07; rom[12:16] = bytes(4)
    if battery: rom[6] |= 0x02
    open(out, 'wb').write(rom)
    return rom

NONZERO_FREE = {(15, 0xDBF3), (15, 0xDC63), (0, 0xBED0)}   # $DBF3-$DC3A: unused table entries (free-space study, verified; never read in the traces)
def check_free(rom):
    """verify patches placed in 'free' areas stay inside them and report the room left"""
    orig = open(SRC, 'rb').read()
    for bank, areas in FREE.items():
        base = 0xC000 if bank == 15 else 0x8000
        for a, b in areas:
            o = 16 + bank * 0x4000 + (a - base)
            n = b - a + 1
            if (bank, a) in NONZERO_FREE:   # verified unused, but not zero: report the bytes that differ from the original
                last = max([i for i in range(n) if rom[o + i] != orig[o + i]], default=-1)
                print(f'  free area bank {bank:X} ${a:04X}-${b:04X}: {n} bytes (unused data), changed up to +{last+1}')
                continue
            assert set(orig[o:o + n]) == {0}, 'area not empty in original'
            last = max([i for i in range(n) if rom[o + i] != 0], default=-1)
            print(f'  free area bank {bank:X} ${a:04X}-${b:04X}: {n} bytes, used up to +{last+1}')

if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    def opt(name):
        if name in args:
            k = args.index(name); v = args[k + 1]; del args[k:k + 2]; return v
    only = opt('--only'); only = only.split(',') if only else None
    skip = opt('--skip'); skip = tuple(skip.split(',')) if skip else ()
    out = opt('--out')
    flags = {a for a in args if a.startswith('--')}
    pos = [a for a in args if not a.startswith('--')]
    if not pos: sys.exit(__doc__)
    SRC = pos[0]
    import hashlib
    if hashlib.sha1(open(SRC, 'rb').read()).hexdigest() != 'a91cf3ff63dd7a45c8c83bc0e192c1011d217609':
        print('warning: this is not the expected Strider (USA) ROM (sha1 a91cf3ff...), the build may fail')
    tiles = '--tiles' in flags
    if tiles: skip = tuple(skip) + ('save', 'text')        # the experiment uses the same free bytes
    preload = '--preload' in flags                         # section 13
    glue = '--glue' in flags                               # original ceiling behaviour
    retime = '--retime' in flags                           # title re-timing
    if retime:
        assert not tiles and 'intro' not in skip and 'text' not in skip, '--retime needs the boot sequence and the text patch'
    os.makedirs(OUTDIR, exist_ok=True)
    if not out:
        combo = [n for n, on in (('title retime', retime), ('ceiling glue', glue), ('enemy tiles preload', preload)) if on]
        out = OUT if not combo else os.path.join(OUTDIR, 'Strider Repolished [%s].nes' % ' + '.join(combo))
    rom = build(only, out=out, tiles=tiles, skip=skip, preload=preload, glue=glue, retime=retime)
    check_free(rom)
    print('wrote', out)
