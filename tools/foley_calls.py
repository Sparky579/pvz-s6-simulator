"""Observe original Foley sample-selection callers without changing RNG."""
import struct

def trace_foley_calls(e):
    m=e.memory;hook=0x515188;callback=e.BASE+0xc00;count=e.SHARED+0x60;log=m.alloc(0x40000)
    expected=e.asm('call 0x5af400',hook)
    if m.read(hook,5)!=expected:raise RuntimeError('Foley callsite changed')
    foley=m.u32(e.lawn+0x784)
    code=f'''
        pushfd
        pushad
        mov eax,dword ptr [0x{e.ELAPSED:x}]
        cmp eax,940
        jb done
        cmp eax,946
        ja done
        mov ebx,dword ptr [0x{count:x}]
        cmp ebx,256
        jae done
        mov edi,ebx
        shl edi,10
        add edi,0x{log:x}
        stosd
        mov eax,dword ptr [esp+16]
        sub eax,0x{foley:x}
        xor edx,edx
        mov ecx,0xa4
        div ecx
        stosd
        mov eax,dword ptr [esp+28]
        stosd
        mov ebp,dword ptr [esp+8]
        mov eax,dword ptr [ebp+4]
        stosd
        mov eax,ebp
        stosd
        lea esi,[esp+36]
        mov ecx,128
        rep movsd dword ptr es:[edi],dword ptr [esi]
        inc dword ptr [0x{count:x}]
    done:
        popad
        popfd
        jmp 0x5af400
    '''
    m.write(callback,e.asm(code,callback));m.write(hook,e.asm(f'call 0x{callback:x}',hook))
    def get():
        result=[]
        for i in range(min(m.u32(count),256)):
            data=m.read(log+i*1024,532);v=struct.unpack('<133I',data)
            result.append({'frame':v[0],'kind':v[1],'range':v[2],'foley_caller':v[3],'ebp':v[4],'stack':list(v[5:])})
        return result
    return get
