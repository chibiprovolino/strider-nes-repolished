"""Revised English script (src/revised.json, not distributed here) -> ROM.

Dialogue / monitor messages (table bank 7 $88D9) and story screens (table bank 7 $97BD) are rewritten and
repacked inside the three runs of bank 7 that hold nothing but those messages; every table entry that pointed at a
message is pointed at its new place.  Other messages that sit between the runs ("KEY NO.x ACQUIRED", $9773...) stay
where they are, except the three that sit at the edges of the runs, which join them: KEY / FILE ACQUIRED ($8F31-$901C),
the "MR. KAIN" taunt at $9773 (its last two bytes, F9 FF, are also story table entry 0 at $97BD and stay there) and
"THE NEXT STORY!" ($9E56).  Labels: status screen item names (LABELS) and the bank 7 name tag / menu labels ('l' keys,
line ends in bit 7, then $FE) are written in place, no longer than the original.
"""
import json, os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
REVISED = os.path.join(HERE, 'revised.json')

def available(): return os.path.exists(REVISED)

def load_entries(src):
    """message table metadata, extracted from the original ROM by build_entries.py (cached in build/)"""
    p = os.path.join(os.path.dirname(HERE), 'build', 'entries.json')
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        subprocess.run([sys.executable, os.path.join(HERE, 'build_entries.py'), src, p], check=True, stdout=subprocess.DEVNULL)
    return json.load(open(p))
DTAB, STAB = 0x88D9, 0x97BD
ZONES = [(0x8B71, 0x9773), (0x9773, 0x97BD), (0x97D7, 0x9E69)]   # [start, end)
OVERRUN = {0x97BD: b'\xF9\xFF'}    # the last message of a zone may end in these bytes after it (left in place)
NIDS = 0x7F                     # table ids 1..$7E ($7F points at $0000)
FIXES = {'s05': [('HYRIU', 'HIRYU')], 'm26': [('STRENGHT', 'STRENGTH')], 'm58': [('SISTER  WAS', 'SISTER WAS')]}
HUB = {'?': 0x60, '!': 0x61, '"': 0x62, "'": 0x67, ',': 0x6C, '-': 0x6D, '.': 0x6E, ' ': 0x40}
TAIL = "DON'T MISS IT!"
# control code $F5 (story / dialogue typewriter, bank 7 $82C8; unused by the game's text - its old handler $83CE
# waited for an event and restarted the text) becomes 'continue reading at lo hi', like $FA / $FE move $19/$1A
F5_SLOT = 0x82E3            # jump table after JSR $C003 at $82D6: entry = handler - 1, code $F0+n at $82D9+2n
F5_CODE = bytes([0xAC, 0x8C, 0x05,   # LDY $058C      index of the $F5
                 0xC8, 0xB1, 0x19,   # INY / LDA ($19),Y
                 0x48,               # PHA
                 0xC8, 0xB1, 0x19,   # INY / LDA ($19),Y
                 0x85, 0x1A,         # STA $1A
                 0x68, 0x85, 0x19,   # PLA / STA $19
                 0xA9, 0x00,         # LDA #0
                 0x8D, 0x8C, 0x05,   # STA $058C
                 0x4C, 0xC8, 0x82])  # JMP $82C8      next byte
LABELS = {'i03': (1, 0xB5D9, 5)}

def off(bank, a): return 16 + bank * 0x4000 + (a & 0x3FFF)

def pages_of(text):
    pg = [[]]
    for l in text.split('\n'):
        if l.strip() == '---': pg.append([]); continue
        pg[-1].append(l.rstrip())
    out = []
    for p in pg:
        while p and p[-1] == '': p.pop()
        while p and p[0] == '': p.pop(0)
        if p: out.append(p)
    return out

def chars(s, hub, f6=False):
    b = bytearray()
    for c in s:
        if f6:   # font after $F6 (m62, Red Dragon): the hub codes + $10, '.' = $73
            b.append(0x73 if c == '.' else (HUB[c] if c in HUB else ord(c)) + 0x10); continue
        if hub and c in HUB: b.append(HUB[c]); continue
        o = ord(c)
        assert 0x20 <= o < 0x60, f'character {c!r} has no tile'
        b.append(o)
    return bytes(b)

def msg_len(rom, a):
    k = 0
    while True:
        c = rom[off(7, a + k)]; k += 1
        if c == 0xFA: k += 2; continue
        if c in (0xFF, 0xF8): return k

def encode(kind, orig, text, cols, rows):
    """kind dialogue/monitor/story; orig = original bytes (prefix F7 / FA xxxx kept)"""
    pg = pages_of(text)
    for p in pg:
        for l in p: assert len(l) <= cols, f'line too long ({len(l)} > {cols}): {l!r}'
        assert len(p) <= rows, f'{len(p)} lines > {rows}: {p}'
    if kind == 'line':          # FA lo hi, one line, FF
        assert len(pg) == 1 and len(pg[0]) == 1, f'one line only: {pg}'
        assert orig[0] == 0xFA
        return bytes(orig[:3]) + chars(pg[0][0], False) + b'\xFF'
    if kind == 'story':
        lines = [l for p in pg for l in p]
        if lines[-1] == TAIL:   # '$F5 lo hi' = go on reading at the one shared copy (see apply)
            return b'\xFE'.join(chars(l, False) for l in lines[:-1]) + b'\xFE\xF5\x00\x00'
        return b'\xFE'.join(chars(l, False) for l in lines) + b'\xFF'
    i = 0; pre = bytearray()
    if orig[0] in (0xF7, 0xF6): pre.append(orig[0]); i = 1
    f6 = orig[0] == 0xF6
    assert orig[i] == 0xFA; pre += orig[i:i + 3]
    hub = kind == 'monitor'
    body = bytearray()
    for n, p in enumerate(pg):
        if n and not hub: body.append(0xF9)
        body += b'\xFE'.join(chars(l, hub, f6) for l in p) + b'\xFC'
        if hub: body.append(0xF9)
    body.append(0xFF if hub else 0xF8)
    return bytes(pre + body)

def apply(rom, verbose=True, extra=None, src='Strider (USA).nes'):
    """extra: more {key: [(old, new)]} substitutions for one build variant (build.py --retime)"""
    rom = bytearray(rom)
    ent = {e['key']: e for e in load_entries(src)}
    rev = json.load(open(REVISED))
    fixes = {k: list(v) for k, v in FIXES.items()}
    for k, subs in (extra or {}).items():
        for a, b in subs:
            assert k in rev and a in rev[k], f'extra fix {k}: {a!r} not found'
        fixes.setdefault(k, []).extend(subs)
    for k, subs in fixes.items():
        for a, b in subs:
            if k in rev and a in rev[k]: rev[k] = rev[k].replace(a, b)
    w = lambda a: rom[off(7, a)] | rom[off(7, a + 1)] << 8
    tabs = [(DTAB + 2 * i) for i in range(1, NIDS)] + [(STAB + 2 * i) for i in range(1, 13)]
    # key -> address of the message
    addr_of = {}
    for k, e in ent.items():
        if e['kind'] in ('dialogue', 'monitor', 'story', 'line'):
            addr_of[k] = int(e['where'].split('$')[1][:4], 16)
    new = {}; report = []
    for k, t in rev.items():
        e = ent[k]
        if e['kind'] == 'label' and k[0] == 'l':
            a0 = int(k[1:], 16); n = int(e['where'].split('(')[1].split()[0])
            old = bytes(rom[off(7, a0):off(7, a0) + n]); assert old[-1] == 0xFE, (k, old.hex())
            lines = [l.rstrip() for l in t.split('\n')]
            while lines and not lines[-1]: lines.pop()
            hb = old.rstrip(b' \xFE')[-1] & 0x80             # original ends its last line with bit 7 too
            b = bytearray()
            for j, l in enumerate(lines):
                c = bytearray(chars(l, False)); assert c, f'{k}: empty line'
                if j < len(lines) - 1 or hb: c[-1] |= 0x80
                b += c
            assert len(b) <= n - 1, f'{k}: {len(b)} bytes, room {n - 1}'
            rom[off(7, a0):off(7, a0) + n] = bytes(b) + b' ' * (n - 1 - len(b)) + b'\xFE'
            report.append(f'  text      bank 7 ${a0:04X}: {k} in place, {len(b)} of {n - 1} bytes')
            continue
        if e['kind'] == 'label':
            assert k in LABELS, f'{k}: changing this label is not supported yet'
            bank, a, n = LABELS[k]
            assert len(t) == n, (k, t)
            rom[off(bank, a):off(bank, a) + n] = chars(t, False)
            continue
        a = addr_of[k]
        orig = bytes(rom[off(7, a):off(7, a) + msg_len(rom, a)])
        b = encode(e['kind'], orig, t, e['cols'], e['rows'])
        if not any(z0 <= a < z1 for z0, z1 in ZONES):   # m62 ($8A28): stays where it is
            assert len(b) <= len(orig), f'{k}: {len(b)} bytes, room {len(orig)}'
            if orig[0] == 0xF6:
                seen = set(orig[4:])
                for c in b[4:]: assert c in seen or 0x51 <= c <= 0x6A, f'{k}: code ${c:02X} not in the original font set'
            rom[off(7, a):off(7, a) + len(orig)] = b + bytes(len(orig) - len(b))
            report.append(f'  text      bank 7 ${a:04X}: {k} in place, {len(b)} of {len(orig)} bytes')
            continue
        new[a] = b
    blobs = {}                                          # old address -> new bytes
    for z0, z1 in ZONES:
        starts = sorted({w(t) for t in tabs if z0 <= w(t) < z1})
        pos = z0                                        # every byte of the zone belongs to a message
        for a in starts:
            assert a == pos, f'zone ${z0:04X}: unknown bytes at ${pos:04X}'
            n = msg_len(rom, a); pos += n
            blobs[a] = new.get(a) or bytes(rom[off(7, a):off(7, a) + n])
        if pos > z1 and z1 in OVERRUN:
            assert pos == z1 + len(OVERRUN[z1]) and bytes(rom[off(7, z1):off(7, pos)]) == OVERRUN[z1], hex(pos)
            pos = z1
        assert pos == z1, (hex(pos), hex(z1))
    EXTRA = -1                                          # shared tail + $F5 handler
    if any(b.endswith(b'\xF5\x00\x00') for b in blobs.values()):
        blobs[EXTRA] = chars(TAIL, False) + b'\xFF' + F5_CODE
    # the three zones are one pool (pointers are absolute): best fit, biggest first
    room = {z: z[1] - z[0] for z in ZONES}; where = {z: [] for z in ZONES}
    for a in sorted(blobs, key=lambda a: (-len(blobs[a]), a)):
        fit = [z for z in ZONES if room[z] >= len(blobs[a])]
        assert fit, f'text does not fit: {sum(map(len, blobs.values()))} bytes, room {sum(z1 - z0 for z0, z1 in ZONES)}'
        z = min(fit, key=lambda z: room[z]); room[z] -= len(blobs[a]); where[z].append(a)
    moved = {}
    for (z0, z1), lst in where.items():
        p = z0
        for a in sorted(lst, key=lambda a: a if a >= 0 else 1 << 20):
            moved[a] = p; p += len(blobs[a])
        report.append(f'  text      bank 7 ${z0:04X}-${z1-1:04X}: {p - z0} of {z1 - z0} bytes')
    if EXTRA in moved:
        tail = moved[EXTRA]; code = tail + len(TAIL) + 1
        for a, b in blobs.items():
            if a != EXTRA and b.endswith(b'\xF5\x00\x00'): blobs[a] = b[:-2] + bytes([tail & 0xFF, tail >> 8])
        assert bytes(rom[off(7, F5_SLOT):off(7, F5_SLOT) + 2]) == bytes([0xCD, 0x83])
        rom[off(7, F5_SLOT)] = (code - 1) & 0xFF; rom[off(7, F5_SLOT) + 1] = (code - 1) >> 8
        report.append(f'  text      bank 7 ${tail:04X}: shared "{TAIL}"; ${code:04X}: code $F5 (slot ${F5_SLOT:04X})')
    for z0, z1 in ZONES: rom[off(7, z0):off(7, z1)] = bytes(z1 - z0)
    for a, p in moved.items(): rom[off(7, p):off(7, p) + len(blobs[a])] = blobs[a]
    old = {t: w(t) for t in tabs}
    for t, a in old.items():
        if a in moved: rom[off(7, t)] = moved[a] & 0xFF; rom[off(7, t) + 1] = moved[a] >> 8
    if verbose: print('\n'.join(report))
    return rom
