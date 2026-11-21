"""Strider (USA) message tables -> entries.json (metadata the text patch needs).  usage: build_entries.py rom out.json"""
import json
import sys; rom = open(sys.argv[1], 'rb').read()[16:]; OUTF = sys.argv[2]
def rd(b, a): return rom[b * 0x4000 + (a & 0x3FFF)]
def w(b, a): return rd(b, a) | rd(b, a + 1) << 8
HUBP = {0x60: '?', 0x61: '!', 0x62: '"', 0x67: "'", 0x6C: ',', 0x6D: '-', 0x6E: '.'}

def ch(c, hub=False, off=0):
    c -= off
    if c in (0x20, 0x40): return ' '
    if hub and c in HUBP: return HUBP[c]
    if c == 0x63 and off: return '.'
    return chr(c) if 0x21 <= c < 0x60 else '?'

def typewriter(b, p, hub=False):
    """BG typewriter message -> (pages[list of lines], start column, raw length)"""
    pages, line, k, col, off = [[]], '', 0, None, 0
    while True:
        c = rd(b, p + k); k += 1
        if c == 0xFA:
            a = rd(b, p + k) | rd(b, p + k + 1) << 8; k += 2
            if col is None: col = a & 0x1F
            continue
        if c == 0xF6: off = 0x10; continue
        if c >= 0xF4:
            if c == 0xFE: pages[-1].append(line); line = ''
            elif c == 0xFC:
                pages[-1].append(line); line = ''
            elif c == 0xF9:
                if pages[-1]: pages.append([])
            elif c in (0xFF, 0xF8): break
            continue
        line += ch(c, hub, off)
    if line: pages[-1].append(line)
    pages = [pg for pg in pages if pg]
    for pg in pages:
        while pg and pg[-1] == '': pg.pop()
    return pages, col, k

out = []
def add(sec, kind, key, pages, where, ids=None, ctx='', cols=None, rows=None, fixed=False, note=''):
    out.append(dict(sec=sec, kind=kind, key=key, pages=pages, where=where, ids=ids or [], ctx=ctx,
                    cols=cols, rows=rows, fixed=fixed, note=note))

# ---- dialogue messages (table bank 7 $88D9), deduped by pointer
ptr_ids = {}
for i in range(1, 0x7F):          # $7F points at $0000
    ptr_ids.setdefault(w(7, 0x88D9 + 2 * i), []).append(i)
def msg(i):
    p = w(7, 0x88D9 + 2 * i)
    hub = rd(7, p) != 0xF7
    pages, col, n = typewriter(7, p, hub)
    return p, pages, col, n, hub
def dlg(sec, i, ctx='', note='', rows=None):
    p, pages, col, n, hub = msg(i)
    ids = ptr_ids[p]
    kind = 'monitor' if hub else 'dialogue'
    cols = (22 if hub else 26 - (col or 3))
    add(sec, kind, 'm%02X' % i, pages, 'bank 7 $%04X (%d bytes)' % (p, n), ['$%02X' % x for x in ids], ctx,
        cols, rows or (4 if hub else 5), note=note)

def line_msg(sec, i, ctx='', note=''):
    p = w(7, 0x88D9 + 2 * i)          # FA lo hi, plain font, FF; one line at a fixed column
    pages, col, n = typewriter(7, p)
    add(sec, 'line', 'm%02X' % i, pages, 'bank 7 $%04X (%d bytes)' % (p, n), ['$%02X' % i], ctx, 32 - col - 2, 1, note=note)

def story(sec, i, ctx=''):
    p = w(7, 0x97BD + 2 * i)
    pages, col, n = typewriter(7, p)
    lines = [l for pg in pages for l in pg]
    add(sec, 'story', 's%02X' % i, [lines], 'bank 7 $%04X (%d bytes)' % (p, n), ['story $%02X' % i], ctx, 28, 12)

def fixed_str(sec, key, text, where, ctx='', note=''):
    lines = text if isinstance(text, list) else [text]
    add(sec, 'label', key, [lines], where, ctx=ctx, cols=max(len(l) for l in lines), rows=len(lines), fixed=True, note=note)

def label(sec, a0, a1, ids, ctx='', note=''):
    lines, line = [], ''
    for a in range(a0, a1):
        c = rd(7, a)
        if c == 0xFE: break
        line += ch(c & 0x7F)
        if c & 0x80: lines.append(line); line = ''
    if line.strip(): lines.append(line)
    lines = [l.rstrip() for l in lines]
    while lines and not lines[-1]: lines.pop()
    add(sec, 'label', 'l%04X' % a0, [lines], 'bank 7 $%04X-$%04X (%d bytes, line ends packed into the last letter)' % (a0, a1 - 1, a1 - a0),
        ['$%02X' % x for x in ids], ctx, cols=max(len(l) for l in lines), rows=len(lines), fixed=True, note=note)

def boots(sec, a, ctx):
    pages, col, n = typewriter(7, a)
    add(sec, 'dialogue', 'b%04X' % a, pages, 'bank 7 $%04X (%d bytes)' % (a, n), [], ctx, 26 - (col or 4), 1)

S0 = 'Title screen'
fixed_str(S0, 't1', 'GAME START', 'bank 7 $8765')
fixed_str(S0, 't2', 'PASSWORD', 'bank 7 $8772', note='The current build shows CONTINUE here (save patch).')
fixed_str(S0, 't3', 'TM AND ©1989', 'bank 7 $8782', note='Legal line.')
fixed_str(S0, 't4', 'CAPCOM U.S.A, INC.', 'bank 7 $8791', note='Legal line; the ROM really has "U.S.A," with no period.')
fixed_str(S0, 't5', 'LICENSED BY', 'bank 7 $87A6', note='Legal line.')
fixed_str(S0, 't6', 'NINTENDO OF AMERICA.INC.', 'bank 7 $87B4', note='Legal line.')

S = 'Prologue'
story(S, 1, 'Story screen shown before the first mission')

S = 'Blue Dragon: first briefing'
dlg(S, 0x55, 'The chief gives Hiryu his orders')
dlg(S, 0x56, "Hiryu's answer")

S = 'Blue Dragon: menus and screens'
fixed_str(S, 'h1', ['TRANS', '  FER'], 'bank 1 $B6E8', 'Hub menu', 'Current build: SAVE / GAME instead of PASS / WORD.')
fixed_str(S, 'h2', ['ANA', ' LYZE'], 'bank 1 $B6E8', 'Hub menu')
fixed_str(S, 'h3', ['PASS', ' WORD'], 'bank 1 $B6E8', 'Hub menu', 'Current build: SAVE / GAME.')
label(S, 0x8AA3, 0x8AAA, [0x31], 'Transfer destination')
label(S, 0x8AAA, 0x8AB6, [0x32], 'Transfer destination')
label(S, 0x8AB6, 0x8ABC, [0x33], 'Transfer destination')
label(S, 0x8ABC, 0x8AC2, [0x34], 'Transfer destination')
label(S, 0x8AC2, 0x8AC8, [0x35], 'Transfer destination')
label(S, 0x8AC8, 0x8ACF, [0x36], 'Transfer destination')
label(S, 0x8ACF, 0x8ADB, [0x37, 0x38], 'Transfer destination')
label(S, 0x8ADB, 0x8AE6, [0x39], 'Transfer destination')
label(S, 0x8B5A, 0x8B71, [0x2F, 0x30], 'Transfer confirmation')
label(S, 0x8B40, 0x8B5A, [0x45], 'Analyze screen')
for k, a in enumerate(range(0x8AE6, 0x8B40, 15)):
    label(S, a, a + 15, [0x46 + k], 'Analyze screen')
label(S, 0x8A8A, 0x8A97, [0x3A] + list(range(0x3B, 0x45)) + [0x52, 0x60], 'Name tag')
label(S, 0x8A97, 0x8AA3, [0x53], 'Name tag')
label(S, 0x8A6C, 0x8A7C, [0x61], 'Password entry')
label(S, 0x8A7C, 0x8A8A, [0x63], 'Password entry')
# status / item screen (bank 1 $B6xx, $FB = new line, $FD = position)
for key, t, a in [('i01', 'SLIDE IN', 0xB437), ('i02', 'PLASMA ARROW', 0xB440), ('i03', 'TRICK', 0xB5D9),
                  ('i04', 'FIRE', 0xB5E0), ('i05', 'MEDICAL', 0xB5E8), ('i06', 'SPARK', 0xB5F3), ('i07', 'JUMP', 0xB5FC),
                  ('i08', 'WARP', 0xB604), ('i09', 'GROUND', 0xB611), ('i10', 'MEDICAL', 0xB61B), ('i11', 'SP-BALL', 0xB62A),
                  ('i12', 'MEDICAL', 0xB635), ('i13', 'LEVEL', 0xB641), ('i14', 'H.MAX', 0xB648), ('i15', 'E.MAX', 0xB64F),
                  ('i16', 'S.LEVEL', 0xB656), ('i17', 'DATA FILE', 0xB668), ('i18', 'KEY', 0xB688)]:
    fixed_str(S, key, t, 'bank 1 $%04X' % a, 'Status screen')

S = 'Kazakh'
dlg(S, 0x01, 'A soldier begs for his life')
dlg(S, 0x04, 'The Kazakh commander')
dlg(S, 0x4D, 'Data file: an intercepted message')
story(S, 2, 'Story screen after the mission')

S = 'The Kain rescue mission'
dlg(S, 0x08, 'An enemy hands over an item')
boots(S, 0x89D9, 'Item pickup')
story(S, 3, 'Story screen')

S = 'Egypt: the pyramid'
story(S, 4, 'Story screen after the key is found')

S = 'The reunion'
dlg(S, 0x06, 'Hiryu finds Kain')
dlg(S, 0x58, 'Hiryu at the base, after the rescue')
dlg(S, 0x4E, 'Data file')
story(S, 5, 'Story screen')

S = 'Japan'
dlg(S, 0x4F, 'The chief explains Zain')
dlg(S, 0x0C, 'The chief, in Japan')
dlg(S, 0x2D, 'Ryuzaki, a fellow Strider', 'Message $2F shows the TRANSFER prompt first, then this same text.')
story(S, 6, 'Story screen')

S = 'China'
boots(S, 0x8A0D, 'Item pickup')
dlg(S, 0x0E, 'After a Zain terminal is destroyed')
story(S, 7, 'Story screen')

S = 'Kazakh: infiltration'
dlg(S, 0x1E, 'Guards loyal to the vice director')
dlg(S, 0x10, 'Matic appears')
dlg(S, 0x0D, 'After the fight')
story(S, 8, 'Story screen')

S = 'Africa'
dlg(S, 0x50, 'Data file: the Matic unit reports to Faceas Clay')
dlg(S, 0x2B, 'A Strider loyal to Matic')
dlg(S, 0x20, 'Cipher upgrade')
dlg(S, 0x22, 'An ally hands Hiryu an item')
story(S, 9, 'Story screen')

S = 'Australia'
dlg(S, 0x51, 'Data file: Faceas Clay')
dlg(S, 0x5B, 'News from the base')
dlg(S, 0x5E, 'Hiryu looks for Sheena')
boots(S, 0x89F2, 'Item pickup')
story(S, 0x0A, 'Story screen')

S = 'Los Angeles'
dlg(S, 0x14, 'Locked door')
dlg(S, 0x26, 'Behind the tempered glass')
dlg(S, 0x2A, 'The enemy is beaten')
dlg(S, 0x24, 'Kain, wounded')
dlg(S, 0x54, 'Kain, dying, at the base')
story(S, 0x0B, 'Story screen')

S = 'The Red Dragon'
dlg(S, 0x62, 'Arrival', "Drawn with this level's own font (codes +$10); the last mark on each page is probably a period.")
dlg(S, 0x1B, 'A guardian')
dlg(S, 0x1D, 'Warning')
dlg(S, 0x17, 'Advice before the final fall')
dlg(S, 0x19, 'The main tree revealed')

S = 'Pickups and other messages'
for i in range(0x6C, 0x70): dlg(S, i, 'Key pickup', 'There is no KEY NO.1 message in the ROM.' if i == 0x6C else '', rows=1)
for i in range(0x70, 0x76): dlg(S, i, 'Data file pickup', rows=1)
dlg(S, 0x76, 'An enemy taunts Hiryu', 'Shown on the monitor screen. Where it appears in the game is not confirmed yet.')
line_msg(S, 0x7B, 'One line, starts at a fixed column')

S = 'Ending'
story(S, 0x0C, 'Ending text')
cred = [('c1', 'GAME DESIGN', 0xBF35), ('c2', 'PATARIRO', 0xBF41), ('c3', 'ADVICE', 0xBF4A), ('c4', 'ALL', 0xBF51),
        ('c5', 'CHARACTER DESIGN', 0xBF55), ('c6', 'VAMPIRE.M', 0xBF66), ('c7', 'TERUKUN', 0xBF70), ('c8', 'LINDA', 0xBF78),
        ('c9', 'MUSIC COMPOSE', 0xBF7E), ('c10', 'MISSES TARUMI', 0xBF8C), ('c11', 'SUB MEMBERS', 0xBF9A), ('c12', 'TANUKI', 0xBFA6),
        ('c13', 'MARIRINE', 0xBFAD), ('c14', 'PROGRAMMER', 0xBFB6), ('c15', 'ZAC', 0xBFC2), ('c16', 'MAMICYAN\\OTONA', 0xBFC5),
        ('c17', 'BY CAPCOM', 0xBFD4)]
heads = ('c1', 'c3', 'c5', 'c9', 'c11', 'c14', 'c17')
for key, t, a in cred:
    add(S, 'label', key, [[t]], 'bank 1 $%04X (length-prefixed)' % a, ctx='Staff roll', rows=1,
        note='' if key in heads else 'Staff nickname: change only if you mean to.')

used = {e['key'] for e in out}
missing = sorted({'m%02X' % ids[0] for p, ids in ptr_ids.items()} - used)
print('dialogue pointers not placed:', missing)
json.dump(out, open(OUTF, 'w'), indent=0)
print(len(out), 'entries')
