from __future__ import annotations
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .aa import Assembler, enable_text

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT/'original/麦版S6本体+ct+修改器'
TABLE = GAME/'S6正赛(bug寒).CT'


class Table:
    def __init__(self, path=TABLE):
        self.root = ET.parse(path).getroot()
        self.entries = {int(e.findtext('ID')):e for e in self.root.findall('.//CheatEntry')}

    def core_scripts(self):
        return [e for e in self.entries[3562].iter('CheatEntry') if e.find('AssemblerScript') is not None]

    @staticmethod
    def allocation_plan(entries):
        """Reserve every CE allocation in full, using page-aligned blocks."""
        offset=0;plans=[]
        for entry in entries:
            plan={}
            allocs=re.findall(r'alloc\(([^,]+),([^,)]+)(?:,[^)]*)?\)',
                              enable_text(entry.findtext('AssemblerScript')),re.I)
            for name,literal in allocs:
                literal=literal.strip()
                size=int(literal[1:],10) if literal.startswith('#') else int(literal,16)
                if not 0<size<=0x7fffffff:raise ValueError(f'Invalid CE allocation size: {literal}')
                name=name.strip()
                if name in plan:raise ValueError(f'Duplicate CE allocation: {name}')
                plan[name]=(offset,size)
                offset+=(size+0xfff)&~0xfff
            plans.append(plan)
        return max(offset,0x1000),plans

    def compile(self, memory=None, extras=(), version='s6-bug', five_mowers=True):
        if version != 's6-bug':
            raise ValueError(f'Unknown version: {version}')
        assembler = Assembler(read_u32=memory.u32 if memory else lambda a:0)
        programs = []
        self.short_overflows=[]
        entries = self.core_scripts()+[self.entries[i] for i in extras]
        self.arena_size,plans=self.allocation_plan(entries)
        arena = memory.alloc(self.arena_size) if memory else 0x10000000
        for e,plan in zip(entries,plans):
            script = e.findtext('AssemblerScript')
            if int(e.findtext('ID')) == 6093 and five_mowers:
                old='call 408BF0\ncmp eax,1\njg g0'
                if script.count(old)!=1:raise ValueError('End-condition patch anchor changed')
                script=script.replace(old,'call 408BF0\ncmp eax,0\njg g0')
            allocations={name:arena+offset for name,(offset,size) in plan.items()}
            try:
                program = assembler.compile(script, allocations)
            except Exception as exc:
                raise RuntimeError(f'CT {e.findtext("ID")} {e.findtext("Description")}: {exc}') from exc
            for address,data in program.writes:
                if arena<=address<arena+self.arena_size:
                    if not any(arena+offset<=address and address+len(data)<=arena+offset+size
                               for offset,size in plan.values()):
                        raise ValueError(f'CT {e.findtext("ID")} writes outside its declared allocation')
            programs.append((int(e.findtext('ID')),program))
            self.short_overflows.extend((int(e.findtext('ID')),)+x for x in assembler.short_overflows)
        return programs
