"""The Auto Assembler subset used by the supplied S6 table.

Numeric literals follow CE: hexadecimal unless prefixed with # (decimal).
Unknown directives/instructions fail closed; no script is silently skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KsError


class AssemblyError(ValueError):
    pass


@dataclass
class Program:
    writes: list[tuple[int, bytes]]
    symbols: dict[str, int]
    threads: list[int]


def enable_text(script: str) -> str:
    # Section names also occur in the generator's comments.
    script = re.split(r"^\s*\[DISABLE\]\s*$", script, flags=re.M | re.I)[0]
    script = re.sub(r"//[^\n]*", "", script)
    script = re.sub(r"\{.*?\}", "", script, flags=re.S)
    return re.sub(r"^\s*\[ENABLE\]\s*$", "", script, flags=re.M | re.I)


REGS = set("eax ebx ecx edx esi edi esp ebp ax bx cx dx si di sp bp al ah bl bh cl ch dl dh cs ds ss es fs gs st".split())
WORDS = set("byte word dword qword tbyte ptr short near far".split()) | REGS
TOKEN = re.compile(r"(?<![\w])(?:#[+-]?\d+|[a-z_0-9]+)(?![\w])", re.I)


class Assembler:
    def __init__(self, symbols=None, read_u32=None):
        self.globals = dict(symbols or {})
        self.read_u32 = read_u32
        self.ks = Ks(KS_ARCH_X86, KS_MODE_32)

    def compile(self, script: str, allocations: dict[str, int]) -> Program:
        # Local label replacement in CE is case sensitive. In the supplied
        # table, "nuts" and "Nuts" are distinct labels in the same script.
        text = enable_text(script)
        text = re.sub(r'"?plantsvszombies(?:\([^)]*\))?\.exe"?', '400000', text,flags=re.I)
        definitions = dict(re.findall(r"define\(([^,]+),([^\)]+)\)", text,re.I))
        declared = set(re.findall(r"label\(([^)]+)\)", text,re.I))
        registered = re.findall(r"(?<!un)registersymbol\(([^)]+)\)", text,re.I)
        thread_names = re.findall(r"createthread\(([^)]+)\)", text,re.I)
        alloc = dict(allocations)
        nodes = []
        labels = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if re.match(r"^(?:alloc|label|registersymbol|createthread|define)\(", line,re.I):
                continue
            if line.endswith(':'):
                name = line[:-1].strip()
                if name in alloc:
                    nodes.append(('org', alloc[name], line))
                elif re.fullmatch('[a-f0-9]+', name,re.I) and name not in declared:
                    nodes.append(('org', int(name, 16), line))
                else:
                    labels[name] = 0
                nodes.append(('label', name, line))
            else:
                # CE accepts a comma immediately after the opcode in record 1314.
                line = re.sub(r'^([a-z]+),', r'\1 ', line,flags=re.I).rstrip(',')
                nodes.append(('code', line, raw))
        env = {**self.globals, **alloc, **labels}

        def number(expression):
            expression = expression.strip()
            if expression in definitions:
                return number(definitions[expression])
            if expression in env:
                return env[expression]
            if expression.lower() in {k.lower() for k in self.globals}:
                return next(v for k,v in self.globals.items() if k.lower()==expression.lower())
            if expression.startswith('#'):
                return int(expression[1:], 10)
            if expression.startswith('(float)'):
                return struct.unpack('<I', struct.pack('<f', float(expression[7:])))[0]
            if expression.startswith('(double)'):
                return struct.unpack('<Q', struct.pack('<d', float(expression[8:])))[0]
            try:
                return int(expression, 16)
            except ValueError:
                raise AssemblyError(f'Unresolved symbol: {expression}') from None

        def normalize(line):
            line = re.sub(r'\((float|double)\)([-+0-9.]+)', lambda m: '0x%x' % number(m[0]), line)
            # CE pointer expressions are resolved at assembly time.
            def nested(m):
                if self.read_u32 is None:
                    raise AssemblyError('Pointer expression needs a live memory reader')
                return '[%x%s]' % (self.read_u32(number(m[1])), m[2])
            line = re.sub(r'\[\[([^\[\]]+)\]([^\[\]]*)\]', nested, line)
            line = re.sub(r'\b(byte|word|dword|qword|tbyte)(?:\s+ptr)?\s*\[',lambda m:m[1].lower()+' ptr [',line,flags=re.I)
            op, _, args = line.partition(' ')
            op = op.lower()
            if op == 'retn':
                op = 'ret'
            if op in ('mov','cmp','add','sub','lea','test','xor','and','or') and ',' not in args:
                args = re.sub(r'\]\s+(?=\S)', '], ', args)
            args = re.sub(r'\b(short|near)\s+', '', args,flags=re.I)
            def replace(m):
                t = m[0]
                if t in env or t in definitions:
                    return '0x%x' % (number(t) & 0xffffffff)
                if t.lower() in WORDS:
                    return t.lower()
                # Already converted float literals.
                if t.lower().startswith('0x'):
                    return t
                return '0x%x' % (number(t) & 0xffffffff)
            args = TOKEN.sub(replace, args)
            if '[' in args and not re.search(r'\b(?:byte|word|dword|qword|tbyte)\b', args):
                # x87 and integer instructions without a sized register default
                # to 32-bit operands in CE's 32-bit Auto Assembler.
                outside = re.sub(r'\[[^\]]*\]', '', args)
                if op.startswith('f') or not (set(re.findall(r'\b[a-z]+\b', outside)) & REGS):
                    args = args.replace('[', 'dword ptr [')
            return op + (' ' + args if args else '')

        def encode(line, pc, forward=False):
            op, _, tail = line.partition(' ')
            op=op.lower()
            if op in ('db', 'dw', 'dd', 'dq'):
                size = {'db':1,'dw':2,'dd':4,'dq':8}[op]
                parts = re.findall(r"'[^']*'|\"[^\"]*\"|[^\s,]+", tail)
                return b''.join(t[1:-1].encode('ascii') if t.startswith(("'",'"')) else
                                (number(t) & ((1 << (size*8))-1)).to_bytes(size,'little') for t in parts)
            if op == 'nop' and tail:
                return b'\x90' * number(tail)
            normalized = normalize(line)
            # CE reserves long encodings for unresolved forward labels (its
            # autoassembler.pas uses apLong). Numeric in-place branches still
            # select short encodings, e.g. the patch at 5309D8.
            cond = dict(zip('jo jno jb jae je jne jbe ja js jns jp jnp jl jge jle jg'.split(),range(16)))
            cond.update(jz=4,jnz=5,jng=14,jnl=13,jpe=10,jpo=11)
            if (op=='jmp' or op in cond) and '[' not in tail and tail.strip().lower() not in REGS:
                expression=normalized.split(' ',1)[1].replace(' ','')
                if not re.fullmatch(r'0x[0-9a-f]+(?:[+-]0x[0-9a-f]+)*',expression,re.I):
                    raise AssemblyError(f'Invalid branch expression: {expression}')
                target=sum((-1 if sign=='-' else 1)*int(value,16) for sign,value in
                           re.findall(r'([+-]?)(0x[0-9a-f]+)',expression,re.I))
                if re.search(r'\bshort\b',tail,re.I):
                    if not -128<=target-pc-2<=127:
                        self.short_overflows.append((line,pc,target,target-pc-2))
                    code=bytes([0xeb if op=='jmp' else 0x70+cond[op],(target-pc-2)&0xff])
                    return code
                if forward or re.search(r'\bnear\b',tail,re.I):
                    prefix=b'\xe9' if op=='jmp' else bytes([0x0f,0x80+cond[op]])
                    return prefix+struct.pack('<I',(target-pc-len(prefix)-4)&0xffffffff)
            try:
                data, _ = self.ks.asm(normalized, pc)
                if data is None:
                    raise AssemblyError(f'Cannot assemble: {normalized}')
                return bytes(data)
            except KsError as e:
                raise AssemblyError(f'{line} -> {normalized}: {e}') from e

        previous = None
        for iteration in range(30):
            pc = None
            writes = []
            self.short_overflows=[]
            defined=set(alloc)
            for kind, value, source in nodes:
                if kind == 'org':
                    pc = value
                elif kind == 'label':
                    if pc is None:
                        raise AssemblyError(f'Label without origin: {source}')
                    env[value] = pc
                    defined.add(value)
                else:
                    if pc is None:
                        raise AssemblyError(f'Instruction without origin: {source}')
                    forward=any(t in labels and t not in defined for t in TOKEN.findall(value))
                    data = encode(value, pc, forward)
                    writes.append((pc, data))
                    pc += len(data)
            fingerprint = (tuple(sorted(env.items())), tuple(writes))
            if fingerprint == previous:
                result = {k:env[k] for k in registered}
                self.globals.update(result)
                merged = []
                for a, b in writes:
                    if merged and merged[-1][0]+len(merged[-1][1]) == a:
                        merged[-1] = (merged[-1][0], merged[-1][1]+b)
                    else:
                        merged.append((a,b))
                return Program(merged, result, [env[t] for t in thread_names])
            previous = fingerprint
        raise AssemblyError('Label layout did not converge')
