"""Minimal two-pass 6502 assembler for ROM patches.

Syntax: one statement per line, ';' comments, 'label:' definitions, 'NAME = expr',
'.org $ADDR', '.db b,b,...', '.dw w,...'. Operands: #imm, zp/abs (size chosen by value;
force absolute with 'a:' prefix), ',X' ',Y', '(zp),Y', '(zp,X)', '(abs)', 'A'.
Expressions: $hex, decimal, %binary, labels, + - , <expr (low byte) >expr (high byte).
"""
import re

OPS = {}
def _d(s):
    for t in s.split(';'):
        o, n, m = t.split(); OPS[(n, m)] = int(o, 16)
_d("00 BRK imp;01 ORA izx;05 ORA zp;06 ASL zp;08 PHP imp;09 ORA imm;0A ASL acc;0D ORA abs;0E ASL abs;10 BPL rel;11 ORA izy;15 ORA zpx;16 ASL zpx;18 CLC imp;19 ORA aby;1D ORA abx;1E ASL abx;20 JSR abs;21 AND izx;24 BIT zp;25 AND zp;26 ROL zp;28 PLP imp;29 AND imm;2A ROL acc;2C BIT abs;2D AND abs;2E ROL abs;30 BMI rel;31 AND izy;35 AND zpx;36 ROL zpx;38 SEC imp;39 AND aby;3D AND abx;3E ROL abx;40 RTI imp;41 EOR izx;45 EOR zp;46 LSR zp;48 PHA imp;49 EOR imm;4A LSR acc;4C JMP abs;4D EOR abs;4E LSR abs;50 BVC rel;51 EOR izy;55 EOR zpx;56 LSR zpx;58 CLI imp;59 EOR aby;5D EOR abx;5E LSR abx;60 RTS imp;61 ADC izx;65 ADC zp;66 ROR zp;68 PLA imp;69 ADC imm;6A ROR acc;6C JMP ind;6D ADC abs;6E ROR abs;70 BVS rel;71 ADC izy;75 ADC zpx;76 ROR zpx;78 SEI imp;79 ADC aby;7D ADC abx;7E ROR abx;81 STA izx;84 STY zp;85 STA zp;86 STX zp;88 DEY imp;8A TXA imp;8C STY abs;8D STA abs;8E STX abs;90 BCC rel;91 STA izy;94 STY zpx;95 STA zpx;96 STX zpy;98 TYA imp;99 STA aby;9A TXS imp;9D STA abx;A0 LDY imm;A1 LDA izx;A2 LDX imm;A4 LDY zp;A5 LDA zp;A6 LDX zp;A8 TAY imp;A9 LDA imm;AA TAX imp;AC LDY abs;AD LDA abs;AE LDX abs;B0 BCS rel;B1 LDA izy;B4 LDY zpx;B5 LDA zpx;B6 LDX zpy;B8 CLV imp;B9 LDA aby;BA TSX imp;BC LDY abx;BD LDA abx;BE LDX aby;C0 CPY imm;C1 CMP izx;C4 CPY zp;C5 CMP zp;C6 DEC zp;C8 INY imp;C9 CMP imm;CA DEX imp;CC CPY abs;CD CMP abs;CE DEC abs;D0 BNE rel;D1 CMP izy;D5 CMP zpx;D6 DEC zpx;D8 CLD imp;D9 CMP aby;DD CMP abx;DE DEC abx;E0 CPX imm;E1 SBC izx;E4 CPX zp;E5 SBC zp;E6 INC zp;E8 INX imp;E9 SBC imm;EA NOP imp;EC CPX abs;ED SBC abs;EE INC abs;F0 BEQ rel;F1 SBC izy;F5 SBC zpx;F6 INC zpx;F8 SED imp;F9 SBC aby;FD SBC abx;FE INC abx")
MNEM = {n for n, _ in OPS}
BRANCH = {'BPL', 'BMI', 'BVC', 'BVS', 'BCC', 'BCS', 'BNE', 'BEQ'}

class AsmError(Exception): pass

def _eval(e, sym, final):
    e = e.strip()
    if e.startswith('<') or e.startswith('>'):
        v = _eval(e[1:], sym, final)          # None: forward reference in the first pass
        return None if v is None else (v & 0xFF if e[0] == '<' else (v >> 8) & 0xFF)
    total = 0; sign = 1
    for tok in re.findall(r'[+-]|[^+-]+', e):
        tok = tok.strip()
        if tok == '+': sign = 1; continue
        if tok == '-': sign = -1; continue
        if tok.startswith('$'): v = int(tok[1:], 16)
        elif tok.startswith('%'): v = int(tok[1:], 2)
        elif tok.isdigit(): v = int(tok)
        elif tok in sym: v = sym[tok]
        elif final: raise AsmError('undefined symbol ' + tok)
        else: v = None
        if v is None: return None
        total += sign * v
    return total

def assemble(src, symbols=None):
    """returns (chunks {addr: bytes}, symbols)"""
    sym = dict(symbols or {})
    lines = []
    for raw in src.splitlines():
        ln = raw.split(';')[0].strip()
        if ln: lines.append(ln)
    out = {}
    for final in (False, True):
        pc = None; out = {}; cur = None; seen = set()
        def emit(bs):
            nonlocal pc, cur
            if pc is None: raise AsmError('no .org')
            if cur is None or cur + len(out[cur]) != pc: cur = pc; out[cur] = bytearray()
            out[cur] += bytes(bs); pc += len(bs)
        for ln in lines:
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', ln)
            if m:
                if m.group(1) in seen: raise AsmError('duplicate label ' + m.group(1))
                seen.add(m.group(1))
                sym[m.group(1)] = pc; ln = m.group(2).strip()
                if not ln: continue
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$', ln)
            if m:
                sym[m.group(1)] = _eval(m.group(2), sym, final); continue
            if ln.lower().startswith('.org'):
                pc = _eval(ln[4:], sym, True); cur = None; continue
            if ln.lower().startswith('.db'):
                emit([(_eval(x, sym, final) or 0) & 0xFF for x in ln[3:].split(',')]); continue
            if ln.lower().startswith('.dw'):
                for x in ln[3:].split(','):
                    v = _eval(x, sym, final) or 0; emit([v & 0xFF, (v >> 8) & 0xFF])
                continue
            parts = ln.split(None, 1); mn = parts[0].upper(); arg = parts[1].strip() if len(parts) > 1 else ''
            if mn not in MNEM: raise AsmError('bad mnemonic: ' + ln)
            if not arg:
                mode = 'imp' if (mn, 'imp') in OPS else 'acc'; emit([OPS[(mn, mode)]]); continue
            if arg.upper() == 'A' and (mn, 'acc') in OPS:
                emit([OPS[(mn, 'acc')]]); continue
            if arg.startswith('#'):
                v = _eval(arg[1:], sym, final) or 0; emit([OPS[(mn, 'imm')], v & 0xFF]); continue
            if mn in BRANCH:
                v = _eval(arg, sym, final)
                off = 0 if v is None else v - (pc + 2)
                if final and not -128 <= off <= 127: raise AsmError('branch out of range: ' + ln)
                emit([OPS[(mn, 'rel')], off & 0xFF]); continue
            m = re.match(r'^\((.+),\s*[Xx]\)$', arg)
            if m: emit([OPS[(mn, 'izx')], (_eval(m.group(1), sym, final) or 0) & 0xFF]); continue
            m = re.match(r'^\((.+)\),\s*[Yy]$', arg)
            if m: emit([OPS[(mn, 'izy')], (_eval(m.group(1), sym, final) or 0) & 0xFF]); continue
            m = re.match(r'^\((.+)\)$', arg)
            if m:
                v = _eval(m.group(1), sym, final) or 0; emit([OPS[(mn, 'ind')], v & 0xFF, v >> 8]); continue
            idx = ''
            m = re.match(r'^(.+),\s*([XxYy])$', arg)
            if m: arg, idx = m.group(1).strip(), m.group(2).lower()
            force = arg.startswith('a:')
            if force: arg = arg[2:]
            v = _eval(arg, sym, final)
            zpm = 'zp' + idx; absm = 'ab' + idx if idx else 'abs'
            usezp = (v is not None and v < 0x100 and not force and (mn, zpm) in OPS)
            if v is None: usezp = False   # forward refs are absolute
            if usezp: emit([OPS[(mn, zpm)], v])
            else:
                if (mn, absm) not in OPS: raise AsmError('bad addressing: ' + ln)
                v = v or 0; emit([OPS[(mn, absm)], v & 0xFF, (v >> 8) & 0xFF])
    return {a: bytes(b) for a, b in out.items()}, sym
