"""Cache exact CT machine code with checked 32-bit relocations.

Building compares three independent assembler layouts, then checks a fourth
mixed layout against the original compiler. Cached payloads never approximate
game rules; relinking must produce the same bytes as compiling the whole CT.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import zlib
from .aa import Program
from .table import ROOT,TABLE,Table

ARENA=0x20000000
LAWN=0x60000000
DELTA=0x10000000
_lock=threading.Lock()
_loaded={}


class Layout:
    def __init__(self,arena,lawn):self.arena=arena;self.lawn=lawn
    def alloc(self,size,address=0):return self.arena
    def u32(self,address):
        if address!=0x6a9ec0:raise ValueError(f'Uncached live pointer 0x{address:x}')
        return self.lawn


def fingerprint(extras,version,five_mowers):
    h=hashlib.sha256(TABLE.read_bytes())
    for name in ('aa.py','table.py','compiled.py'):h.update((ROOT/'s6'/name).read_bytes())
    h.update(json.dumps([list(extras),version,five_mowers]).encode())
    return h.hexdigest()


def relocation_axis(left,right):
    if len(left)!=len(right):raise ValueError('Relocation changed an instruction length')
    result={}
    for i,(a,b) in enumerate(zip(left,right)):
        if a==b:continue
        difference=(b-a)&255
        if difference not in (16,240) or i<3:
            raise ValueError('Relocation is not a 32-bit address adjustment')
        offset=i-3
        if any(abs(offset-other)<4 for other in result):raise ValueError('Overlapping relocations')
        result[offset]=1 if difference==16 else -1
    return result


def build(extras=(5995,),version='s6-bug',five_mowers=True):
    def compile_at(arena,lawn):
        return Table().compile(Layout(arena,lawn),extras,version,five_mowers)
    base=compile_at(ARENA,LAWN)
    moved_arena=compile_at(ARENA+DELTA,LAWN)
    moved_lawn=compile_at(ARENA,LAWN+DELTA)
    table=Table()
    size,_=table.allocation_plan(table.core_scripts()+[table.entries[i] for i in extras])
    entries=[]
    for (entry,p),(ea,pa),(el,pl) in zip(base,moved_arena,moved_lawn):
        if entry!=ea or entry!=el:raise ValueError('CT order changed')
        writes=[]
        for (address,data),(aa,da),(al,dl) in zip(p.writes,pa.writes,pl.writes):
            dynamic=ARENA<=address<ARENA+size
            if aa!=address+(DELTA if dynamic else 0) or al!=address:
                raise ValueError('Unexpected write-origin relocation')
            ra=relocation_axis(data,da);rl=relocation_axis(data,dl)
            offsets=sorted(set(ra)|set(rl))
            if any(b-a<4 for a,b in zip(offsets,offsets[1:])):raise ValueError('Overlapping relocation axes')
            writes.append({'address':address,'data':data.hex(),
                           'relocations':[[o,ra.get(o,0),rl.get(o,0)] for o in offsets]})
        entries.append({'id':entry,'writes':writes,'symbols':p.symbols,'threads':p.threads})
    result={'arena_size':size,'entries':entries}
    # A negative arena delta and unrelated actual LawnApp address prove that
    # relinking did not merely work for the two positive construction deltas.
    test_arena=0x0c300000;test_lawn=0x068e7128
    reference=compile_at(test_arena,test_lawn)
    linked=realize(result,test_arena,test_lawn)
    for (entry,p),(other,q) in zip(reference,linked):
        if entry!=other or p!=q:raise ValueError(f'Cached CT differs from compiler at record {entry}')
    return result


def realize(template,arena,lawn):
    arena_delta=arena-ARENA;lawn_delta=lawn-LAWN
    def relocated_address(address):
        return address+arena_delta if ARENA<=address<ARENA+template['arena_size'] else address
    programs=[]
    for e in template['entries']:
        writes=[]
        for w in e['writes']:
            data=bytearray.fromhex(w['data'])
            for offset,arena_coefficient,lawn_coefficient in w['relocations']:
                old=struct.unpack_from('<I',data,offset)[0]
                value=(old+arena_coefficient*arena_delta+lawn_coefficient*lawn_delta)&0xffffffff
                struct.pack_into('<I',data,offset,value)
            writes.append((relocated_address(w['address']),bytes(data)))
        programs.append((e['id'],Program(writes,
                        {k:relocated_address(v) for k,v in e['symbols'].items()},
                        [relocated_address(a) for a in e['threads']])))
    return programs


def load(extras=(5995,),version='s6-bug',five_mowers=True):
    key=fingerprint(extras,version,five_mowers)
    with _lock:
        if key in _loaded:return _loaded[key]
        directory=ROOT/'.cache-s6';directory.mkdir(exist_ok=True)
        path=directory/(key+'.json.z')
        try:
            payload=json.loads(zlib.decompress(path.read_bytes()))
            if payload['fingerprint']!=key:raise ValueError('Wrong compiled profile')
            template=payload['template']
        except (OSError,ValueError,KeyError,zlib.error):
            template=build(extras,version,five_mowers)
            data=zlib.compress(json.dumps({'fingerprint':key,'template':template},separators=(',',':')).encode())
            temporary=path.with_suffix('.tmp-'+str(os.getpid()))
            temporary.write_bytes(data);os.replace(temporary,path)
        _loaded[key]=template
        return template


def compile_cached(memory,extras=(5995,),version='s6-bug',five_mowers=True):
    template=load(extras,version,five_mowers)
    arena=memory.alloc(template['arena_size'])
    return realize(template,arena,memory.u32(0x6a9ec0))
