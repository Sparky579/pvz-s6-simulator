import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os
import struct
from s6.engine import Engine
from s6.runtime import wine_environment
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_ESP,UC_X86_REG_EAX,UC_X86_REG_EBX,
                              UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
                              UC_X86_REG_EDI,UC_X86_REG_EBP)
from keystone import Ks,KS_ARCH_X86,KS_MODE_32
from s6.aa import Assembler,enable_text
from s6.config import Config
from s6.table import Table
from s6.compiled import Layout,load,realize


class OriginalSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=dict(Table().compile(five_mowers=False))
        cls.five=dict(Table().compile())

    def test_only_game_rule_change_is_one_mower_threshold_byte(self):
        changed=[]
        for entry,p in self.original.items():
            a=p.writes;b=self.five[entry].writes
            self.assertEqual([(x,len(y)) for x,y in a],[(x,len(y)) for x,y in b])
            for (addr,left),(_,right) in zip(a,b):
                changed.extend((entry,addr+i,x,y) for i,(x,y) in enumerate(zip(left,right)) if x!=y)
        self.assertEqual(len(changed),1)
        self.assertEqual((changed[0][0],changed[0][2],changed[0][3]),(6093,1,0))

    def test_in_place_chill_patch_does_not_overwrite_next_instruction(self):
        writes=dict(self.original[3282].writes)
        self.assertEqual(writes[0x5309d8],bytes.fromhex('85 c9 74 02'))
        self.assertEqual(0x5309d8+len(writes[0x5309d8]),0x5309dc)

    def test_case_sensitive_local_labels_execute_separate_paths(self):
        # Actual S6 uses nuts/Nuts in record 1456. CE's replacetoken compares
        # local labels exactly; case folding sent Tall-nut into unrelated code.
        p=Assembler().compile('''[ENABLE]
alloc(newmem,2048)
newmem:
call nuts
call Nuts
jmp finish
nuts:
mov byte [700000],1
ret
Nuts:
mov byte [700001],2
ret
finish:
nop
[DISABLE]
''',{'newmem':0x1000000})
        u=Uc(UC_ARCH_X86,UC_MODE_32)
        u.mem_map(0x1000000,0x1000);u.mem_map(0x700000,0x1000);u.mem_map(0x800000,0x1000)
        u.reg_write(UC_X86_REG_ESP,0x800ff0)
        start,data=p.writes[0];u.mem_write(start,data);u.emu_start(start,start+len(data))
        self.assertEqual(bytes(u.mem_read(0x700000,2)),b'\x01\x02')

    def test_entire_original_core_is_compiled_without_omissions(self):
        self.assertEqual(set(self.original),{int(e.findtext('ID')) for e in Table().core_scripts()})
        self.assertEqual(len(self.original),369)
        for p in self.original.values():
            self.assertTrue(p.writes)
            for address,data in p.writes:
                self.assertGreaterEqual(address,0x400000)
                self.assertLess(len(data),0x10000)

    def test_large_original_allocations_are_fully_reserved_without_overlap(self):
        table=Table()
        entries=table.core_scripts()+[table.entries[5995]]
        size,plans=table.allocation_plan(entries)
        intervals=[]
        for entry,plan in zip(entries,plans):
            for offset,length in plan.values():
                self.assertEqual(offset%0x1000,0)
                intervals.append((offset,offset+length))
            if int(entry.findtext('ID')) in (3625,1456):
                self.assertEqual(plan['newmem'][1],0x20480)
        intervals.sort()
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(intervals,intervals[1:])))
        self.assertLessEqual(intervals[-1][1],size)
        self.assertLess(size,5*1024*1024)

    def test_section_marker_in_ce_comment_does_not_truncate_script(self):
        text=enable_text(Table().entries[6093].findtext('AssemblerScript'))
        self.assertIn('call 408BF0',text)
        self.assertIn('4140F0:',text)
        self.assertNotIn('dealloc(newmem)',text)

    def test_formation_validation_and_no_chill_fix_option(self):
        c=Config.parse({'formation':[[None]*5 for _ in range(5)]})
        self.assertEqual(c.data['version'],'s6-bug')
        self.assertEqual(c.data['speed_mode'],'exact')
        self.assertEqual(Config.parse({**c.data,'speed_mode':'fast'}).data['speed_mode'],'fast')
        with self.assertRaises(ValueError):Config.parse({**c.data,'speed_mode':'unknown'})
        with self.assertRaises(ValueError):Config.parse({'formation':[[7]*4 for _ in range(5)]})
        with self.assertRaises(ValueError):Config.parse({'formation':[[7]*5 for _ in range(5)],'version':'s6-chill-fix'})

    def test_original_runtime_assets_match_supplied_archive(self):
        from s6.assets import verified_assets
        assets=verified_assets()
        self.assertEqual(assets['runtime_asset_count'],4398)
        self.assertEqual(len(assets['runtime_assets_sha256']),64)

    def test_runtime_cannot_inherit_non_chinese_ansi_environment(self):
        with patch.dict(os.environ,{'LC_ALL':'C.UTF-8','LANG':'C.UTF-8'}):
            env=wine_environment('/private/prefix',':192')
            self.assertEqual(env['LC_ALL'],'zh_CN.UTF-8')
            self.assertEqual(env['LANG'],'zh_CN.UTF-8')
            self.assertEqual(env['WINEPREFIX'],'/private/prefix')
            self.assertEqual(env['DISPLAY'],':192')
            self.assertEqual(os.environ['LC_ALL'],'C.UTF-8')

    def test_missing_original_images_fail_closed(self):
        engine=Engine.__new__(Engine)
        images=[0x12345678]*99
        engine.memory=SimpleNamespace(read=lambda address,size:struct.pack('<99I',*images))
        engine.verify_images()
        images[40]=0
        with self.assertRaisesRegex(RuntimeError,'1/99 images null'):
            engine.verify_images()

    def test_cached_machine_code_matches_compiler_at_two_realistic_layouts(self):
        template=load()
        for arena,lawn in ((0x0bd00000,0x068e7128),(0x64000000,0x06e82000)):
            expected=Table().compile(Layout(arena,lawn),(5995,))
            self.assertEqual(realize(template,arena,lawn),expected)

    def test_fast_overlay_preserves_registers_stack_and_original_callbacks(self):
        class Memory:
            def __init__(self):
                self.words={0x6a9ec0:0x200000,0x200320:0x300000,0x300060:0x400000,
                            0x400000:0x500000,0x500000+47*4:0x56ba70,0x656ca8+0x68:0x41acf0}
                self.code={}
            def u32(self,address):return self.words[address]
            def put32(self,address,value):self.words[address]=value
            def write(self,address,data):self.code[address]=data
        e=Engine.__new__(Engine);e.BASE=0x1000000;e.memory=Memory()
        e.ks=Ks(KS_ARCH_X86,KS_MODE_32);e.display_counter=1
        e.set_fast_drawing(True)
        u=Uc(UC_ARCH_X86,UC_MODE_32)
        u.mem_map(e.BASE+0xd000,0x1000);u.mem_map(0x41a000,0x1000);u.mem_map(0x800000,0x1000)
        u.mem_write(e.FAST_DRAW,e.memory.code[e.FAST_DRAW]);u.mem_write(0x41a2a0,b'\xc2\x04\x00')
        registers={UC_X86_REG_EAX:0x11,UC_X86_REG_EBX:0x22,UC_X86_REG_ECX:0x12340000,
                   UC_X86_REG_EDX:0x44,UC_X86_REG_ESI:0x55,UC_X86_REG_EDI:0x66,UC_X86_REG_EBP:0x77}
        for register,value in registers.items():u.reg_write(register,value)
        stack=0x800fe0;stop=0x1a000000;graphics=0x23450000
        u.reg_write(UC_X86_REG_ESP,stack);u.mem_write(stack,struct.pack('<II',stop,graphics))
        calls=[]
        def observe(machine,address,size,_):
            if address==0x41a2a0:
                sp=machine.reg_read(UC_X86_REG_ESP)
                calls.append((machine.reg_read(UC_X86_REG_EDI),struct.unpack('<I',machine.mem_read(sp+4,4))[0]))
        u.hook_add(UC_HOOK_CODE,observe)
        u.emu_start(e.FAST_DRAW,stop)
        self.assertEqual(calls,[(graphics,registers[UC_X86_REG_ECX])])
        for register,value in registers.items():self.assertEqual(u.reg_read(register),value)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP),stack+8)
        self.assertEqual(e.memory.u32(0x500000+47*4),e.FAST_LOCK)
        e.set_fast_drawing(False)
        self.assertEqual(e.memory.u32(0x656ca8+0x68),0x41acf0)
        self.assertEqual(e.memory.u32(0x500000+47*4),0x56ba70)


if __name__=='__main__':unittest.main()
