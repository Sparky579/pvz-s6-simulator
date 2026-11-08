"""Load a prototype audio device separately from the production DLL."""
from s6.table import ROOT


def install(engine,fast=True):
    e=engine;base=e.BASE+0x6000;m=e.memory
    path=('Z:'+str(ROOT/'build/fast_audio_clock.dll').replace('/','\\')).encode('utf-16-le')+b'\0\0'
    m.write(base,path);cursor=base+0x500;strings={}
    for name in ('kernel32.dll','LoadLibraryW','S6AudioInit','S6AudioError','S6AudioBackendValidation'):
        strings[name]=cursor;data=name.encode()+b'\0';m.write(cursor,data);cursor+=len(data)
    e.execute(f'''
        push 0x{strings['kernel32.dll']:x};call dword ptr [0x{e.api['GetModuleHandleA']:x}];
        push 0x{strings['LoadLibraryW']:x};push eax;call dword ptr [0x{e.api['GetProcAddress']:x}];
        push 0x{base:x};call eax;mov ebx,eax;
        push 0x{strings['S6AudioInit']:x};push ebx;call dword ptr [0x{e.api['GetProcAddress']:x}];
        push 0x{e.lawn:x};call eax;mov dword ptr [0x{e.SHARED+0x24:x}],eax;
        push 0x{strings['S6AudioError']:x};push ebx;call dword ptr [0x{e.api['GetProcAddress']:x}];
        mov dword ptr [0x{e.SHARED+0x2c:x}],eax;
        push 0x{strings['S6AudioBackendValidation']:x};push ebx;call dword ptr [0x{e.api['GetProcAddress']:x}];
        mov dword ptr [eax],{int(not fast)};
    ''')
    error=m.u32(e.SHARED+0x24);e.audio_error=m.u32(e.SHARED+0x2c)
    if error or not e.audio_error:raise RuntimeError(f'Fast audio prototype initialization failed: {error}')
