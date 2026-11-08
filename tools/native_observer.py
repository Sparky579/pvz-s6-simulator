"""Load a passive first-chance exception observer in diagnostic runs only."""
from pathlib import Path
import struct
from s6.table import ROOT

class NativeObserver:
    fields='ready code address thread eax ebx ecx edx esi edi ebp esp eip eflags access address_accessed stack_bytes'.split()
    record_size=(17+128)*4

    def __init__(self,engine):
        self.engine=engine;m=engine.memory;base=engine.BASE+0x8000
        path=('Z:'+str(ROOT/'build/observe.dll').replace('/','\\')).encode('utf-16-le')+b'\0\0'
        m.write(base,path);cursor=base+0x600;strings={}
        for name in ('kernel32.dll','LoadLibraryW','S6ObserveInit','S6ExceptionCount','S6Exceptions'):
            strings[name]=cursor;data=name.encode()+b'\0';m.write(cursor,data);cursor+=len(data)
        engine.execute(f'''
            push 0x{strings['kernel32.dll']:x}
            call dword ptr [0x{engine.api['GetModuleHandleA']:x}]
            push 0x{strings['LoadLibraryW']:x}
            push eax
            call dword ptr [0x{engine.api['GetProcAddress']:x}]
            push 0x{base:x}
            call eax
            mov ebx,eax
            mov dword ptr [0x{engine.SHARED+0x40:x}],eax
            test eax,eax
            jz done
            push 0x{strings['S6ObserveInit']:x}
            push ebx
            call dword ptr [0x{engine.api['GetProcAddress']:x}]
            test eax,eax
            jz done
            call eax
            mov dword ptr [0x{engine.SHARED+0x44:x}],eax
            push 0x{strings['S6ExceptionCount']:x}
            push ebx
            call dword ptr [0x{engine.api['GetProcAddress']:x}]
            mov dword ptr [0x{engine.SHARED+0x48:x}],eax
            push 0x{strings['S6Exceptions']:x}
            push ebx
            call dword ptr [0x{engine.api['GetProcAddress']:x}]
            mov dword ptr [0x{engine.SHARED+0x4c:x}],eax
        done:
        ''')
        self.count=m.u32(engine.SHARED+0x48);self.data=m.u32(engine.SHARED+0x4c)
        if not self.count or not self.data or m.u32(engine.SHARED+0x44):
            raise RuntimeError('Passive exception observer did not initialize')

    def records(self):
        m=self.engine.memory;count=min(m.u32(self.count),32);result=[]
        for i in range(count):
            words=struct.unpack('<145I',m.read(self.data+i*self.record_size,self.record_size))
            if not words[0]:continue
            record=dict(zip(self.fields,words[:17]));record['stack']=list(words[17:17+record['stack_bytes']//4])
            result.append(record)
        return result

    def describe_address(self,address):
        for entry,program in self.engine.programs:
            for start,data in program.writes:
                if start<=address<start+len(data):return {'ct_entry':entry,'offset':address-start,'start':start,'end':start+len(data)}
        if 0x400000<=address<0x650000:return {'engine':True}
        return None
