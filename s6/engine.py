from __future__ import annotations
from pathlib import Path
import struct
import time
import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from .memory import Bridge
from .table import GAME, Table


class Engine:
    """Execute on the original game's main thread at LawnApp::Update boundary."""
    HOOK = 0x452650
    BASE = 0x18000000
    TRAMP = BASE+0x1000
    SHARED = BASE+0x2000
    CODE = BASE+0x3000

    def __init__(self, prefix: Path, display=':121'):
        self.memory = m = Bridge(prefix,display)
        self.ks = Ks(KS_ARCH_X86, KS_MODE_32)
        self.original = m.read(self.HOOK,6)
        if self.original != bytes.fromhex('55 8b ec 83 e4 f8'):
            raise RuntimeError(f'Unexpected LawnApp::Update prologue: {self.original.hex()}')
        self.BASE = m.alloc(0x20000)
        self.TRAMP = self.BASE+0x1000
        self.SHARED = self.BASE+0x2000
        self.CODE = self.BASE+0x3000
        pe = pefile.PE(str(GAME/'PlantsVsZombies.exe'))
        self.api={i.name.decode():i.address for d in pe.DIRECTORY_ENTRY_IMPORT for i in d.imports if i.name}
        sleep = next(i.address for d in pe.DIRECTORY_ENTRY_IMPORT for i in d.imports if i.name==b'Sleep')
        m.write(self.TRAMP, self.original+self.asm(f'jmp 0x{self.HOOK+6:x}',self.TRAMP+6))
        gate = f'''
            pushfd
            pushad
            mov dword ptr [0x{self.SHARED+4:x}], 1
        idle:
            cmp dword ptr [0x{self.SHARED+0x14:x}],0
            jg normal
            mov eax, dword ptr [0x{self.SHARED:x}]
            cmp eax, -1
            je leave
            test eax, eax
            jz wait
            pushad
            call eax
            popad
            mov dword ptr [0x{self.SHARED:x}], 0
            jmp idle
        wait:
            push 1
            call dword ptr [0x{sleep:x}]
            jmp idle
        normal:
            cmp dword ptr [0x7013a0],0
            je normal_done
            dec dword ptr [0x{self.SHARED+0x14:x}]
            inc dword ptr [0x{self.SHARED+0x10:x}]
            mov dword ptr [0x{self.SHARED+4:x}],2
            jmp leave
        normal_done:
            mov dword ptr [0x{self.SHARED+0x14:x}],0
            jmp idle
        leave:
            popad
            popfd
            jmp 0x{self.TRAMP:x}
        '''
        m.write(self.BASE,self.asm(gate,self.BASE))
        m.write(self.HOOK,self.asm(f'jmp 0x{self.BASE:x}',self.HOOK)+b'\x90')
        self.wait(lambda:m.u32(self.SHARED+4)==1,10,'main-thread gate')

    def asm(self, source, address=None):
        return bytes(self.ks.asm(source, address if address is not None else self.CODE)[0])

    @staticmethod
    def wait(predicate, timeout, what):
        deadline = time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError(what)
            time.sleep(.005)

    def execute(self, source, timeout=60):
        self.memory.write(self.CODE,self.asm('pushad; '+source+'; popad; ret'))
        self.memory.put32(self.SHARED,self.CODE)
        try:
            self.wait(lambda:self.memory.u32(self.SHARED)==0,timeout,'main-thread command')
        except TimeoutError:
            raise TimeoutError('Main-thread command: '+self.memory.command('C')) from None
        if hasattr(self,'display_counter') and self.memory.u32(self.SHARED+0x84):
            raise RuntimeError('Unsupported change to the original screen image')

    @property
    def lawn(self): return self.memory.u32(0x6a9ec0)

    @property
    def board(self): return self.memory.u32(self.lawn+0x768)

    def verify_environment(self):
        from .runtime import EXPECTED_ACP
        self.execute(f'call dword ptr [0x{self.api["GetACP"]:x}];mov dword ptr [0x{self.SHARED+0x38:x}],eax')
        actual=self.memory.u32(self.SHARED+0x38)
        if actual!=EXPECTED_ACP:
            raise RuntimeError(f'Original Chinese assets require Win32 ACP {EXPECTED_ACP}; got {actual}. '
                               'Install the zh_CN.UTF-8 locale before running Wine.')

    def verify_images(self):
        # The unmodified EXE's 6518B0 loader enumerates newimages into this
        # original array. Missing ANSI filenames used to produce null images.
        images=struct.unpack('<99I',self.memory.read(0x6ff000,99*4))
        missing=[i for i,pointer in enumerate(images) if not pointer]
        if missing:
            raise RuntimeError(f'Original newimages loader left {len(missing)}/99 images null '
                               f'(slots {missing[:12]}). Check the original assets and Chinese locale.')

    def install_table(self, extras=(5995,),version='s6-bug',five_mowers=True):
        from .compiled import compile_cached
        programs = compile_cached(self.memory,extras,version,five_mowers)
        pending=[]
        for entry, program in programs:
            pending.extend(program.writes)
            if program.threads:
                self.memory.batch(pending);pending.clear()
                for address in program.threads:self.execute(f'call 0x{address:x}')
        self.memory.batch(pending)
        self.programs=programs
        self.global_baseline=self.memory.read(0x700000,0x16000)
        return programs

    def clock_audio(self,physical_output=False):
        """Use the original DirectSound logic with a game-tick device clock."""
        from .table import ROOT
        base=self.BASE+0x6000
        path=('Z:'+str(ROOT/'build/audio_clock.dll').replace('/','\\')).encode('utf-16-le')+b'\0\0'
        self.memory.write(base,path)
        strings={}
        cursor=base+0x500
        for s in ('kernel32.dll','LoadLibraryW','S6AudioInit','S6AudioError','S6AudioPhysicalOutput'):
            strings[s]=cursor;data=s.encode()+b'\0';self.memory.write(cursor,data);cursor+=len(data)
        self.execute(f'''
            push 0x{strings['kernel32.dll']:x}
            call dword ptr [0x{self.api['GetModuleHandleA']:x}]
            push 0x{strings['LoadLibraryW']:x}
            push eax
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            push 0x{base:x}
            call eax
            mov ebx,eax
            mov dword ptr [0x{self.SHARED+0x28:x}],eax
            push 0x{strings['S6AudioInit']:x}
            push ebx
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            push 0x{self.lawn:x}
            call eax
            mov dword ptr [0x{self.SHARED+0x24:x}],eax
            push 0x{strings['S6AudioError']:x}
            push ebx
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            mov dword ptr [0x{self.SHARED+0x2c:x}],eax
            push 0x{strings['S6AudioPhysicalOutput']:x}
            push ebx
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            mov dword ptr [eax],{int(physical_output)}
        ''')
        code=self.memory.u32(self.SHARED+0x24)
        self.audio_error=self.memory.u32(self.SHARED+0x2c)
        if code or not self.audio_error:raise RuntimeError(f'Clock audio initialization: {code}')

    def check_audio(self):
        if hasattr(self,'audio_error'):
            error=self.memory.u32(self.audio_error)
            if error:raise RuntimeError(f'Clock audio device error: 0x{error:x}')

    def discard_pixels(self):
        """Discard screen raster output while retaining original draw callbacks."""
        from .table import ROOT
        if getattr(self,'display_3d',True):
            raise RuntimeError('The virtual screen requires the original software renderer')
        base=self.BASE+0xb000
        path=('Z:'+str(ROOT/'build/null_display.dll').replace('/','\\')).encode('utf-16-le')+b'\0\0'
        self.memory.write(base,path)
        strings={};cursor=base+0x600
        for name in ('kernel32.dll','LoadLibraryW','S6NullDisplayInit','S6NullDisplayCalls'):
            strings[name]=cursor;data=name.encode()+b'\0';self.memory.write(cursor,data);cursor+=len(data)
        self.execute(f'''
            push 0x{strings['kernel32.dll']:x}
            call dword ptr [0x{self.api['GetModuleHandleA']:x}]
            push 0x{strings['LoadLibraryW']:x}
            push eax
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            push 0x{base:x}
            call eax
            test eax,eax
            jz failed
            mov ebx,eax
            push 0x{strings['S6NullDisplayInit']:x}
            push eax
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            test eax,eax
            jz failed
            mov dword ptr [0x{self.SHARED+0x80:x}],eax
            push 0x{self.lawn:x}
            call eax
            mov dword ptr [0x{self.SHARED+0x84:x}],eax
            push 0x{strings['S6NullDisplayCalls']:x}
            push ebx
            call dword ptr [0x{self.api['GetProcAddress']:x}]
            mov dword ptr [0x{self.SHARED+0x8c:x}],eax
            jmp done
        failed:
            mov dword ptr [0x{self.SHARED+0x84:x}],-1
        done:
        ''')
        code=self.memory.u32(self.SHARED+0x84)
        if code:raise RuntimeError(f'Null display initialization: {code}')
        self.display_counter=self.memory.u32(self.SHARED+0x8c)
        if not self.display_counter:raise RuntimeError('Null display counter export missing')
        self.present_frames=False

    def reset_foley(self):
        """Define an empty original Foley state as a trial starting condition."""
        self.execute('''
            mov eax,dword ptr [0x6a9ec0]
            mov ebp,dword ptr [eax+0x784]
            mov ebx,dword ptr [0x6a9f04]
        kind:
            mov esi,ebp
            mov edi,8
        slot:
            mov ecx,dword ptr [esi]
            test ecx,ecx
            jz next_slot
            pushad
            mov eax,dword ptr [ecx]
            call dword ptr [eax+4]
            popad
        next_slot:
            add esi,0x14
            dec edi
            jnz slot
            mov ecx,ebp
            call 0x514ed0
            add ebp,0xa4
            dec ebx
            jnz kind
        ''')

    def set_fast_drawing(self,enabled):
        """Keep the original CT overlay at 100 Hz; omit native scene drawing."""
        if not enabled and not hasattr(self,'FAST_DRAW'):return
        if not hasattr(self,'display_counter'):
            raise RuntimeError('Fast drawing requires the original software screen sink')
        if not hasattr(self,'FAST_DRAW'):
            self.FAST_DRAW=self.BASE+0xd000
            self.FAST_LOCK=self.BASE+0xd800
            # Board::Draw: ECX=Board, one Graphics* stack argument, ret 4.
            # Original 41A2A0: EDI=Graphics, one Board* stack argument, ret 4.
            # Its CT 1316 callback retains all target/latch writes each tick.
            self.memory.write(self.FAST_DRAW,self.asm(
                'pushad;mov edi,dword ptr [esp+36];push ecx;call 0x41a2a0;popad;ret 4',self.FAST_DRAW))
            self.memory.write(self.FAST_LOCK,self.asm('xor eax,eax;ret',self.FAST_LOCK))
        board_slot=0x656ca8+0x68
        if self.memory.u32(board_slot) not in (0x41acf0,self.FAST_DRAW):
            raise RuntimeError('Unsupported Board::Draw implementation')
        screen=self.memory.u32(self.memory.u32(self.lawn+0x320)+0x60)
        screen_table=self.memory.u32(screen)
        lock_slot=screen_table+47*4
        if self.memory.u32(lock_slot) not in (0x56ba70,self.FAST_LOCK):
            raise RuntimeError('Unsupported virtual screen lock implementation')
        self.memory.put32(board_slot,self.FAST_DRAW if enabled else 0x41acf0)
        # DrawScreen uses a failed LockSurface only to skip UnlockSurface.
        # The final-screen sink writes no pixels; source-image locks stay native.
        self.memory.put32(lock_slot,self.FAST_LOCK if enabled else 0x56ba70)
        self.fast_drawing=bool(enabled)

    def seed(self, value):
        # Sexy::MTRand global; use the original seeding routine, including its
        # seed=0 -> 0x1105 behavior.
        self.execute(f'mov ecx,{value};call 0x5af420')

    def start_playing(self):
        self.execute('mov esi,dword ptr [0x6a9ec0];call 0x44f6b0')

    def reset_mowers(self):
        self.execute(f'mov ecx,0x4d;mov edx,0x{self.board:x};call 0x41b1d0')

    def plant(self, row, col, type_id, xp=0):
        source=f'''
            mov eax,{row};push -1;push {type_id};push {col};push 0x{self.board:x}
            call 0x40d120
            mov dword ptr [eax+0x114],{xp}
            mov dword ptr [0x{self.SHARED+0xc:x}],eax
        '''
        try:self.execute(source)
        except TimeoutError as e:raise TimeoutError(f'Plant row={row+1} col={col+1} id={type_id}: {e}') from e
        return self.memory.u32(self.SHARED+0xc)

    def instrument_mowers(self):
        self.TIMES=self.BASE+0x2200
        self.ELAPSED=self.SHARED+0x10
        self.MOWER_HOOK=self.BASE+0x500
        hook=0x458e97
        original=bytes.fromhex('c7 46 2c 02 00 00 00')
        if self.memory.read(hook,7)!=original:raise RuntimeError('Mower hook mismatch')
        source=f'''
            mov dword ptr [esi+0x2c],2
            pushfd
            pushad
            mov eax,dword ptr [esi+0x14]
            cmp eax,5
            jae done
            cmp dword ptr [eax*4+0x{self.TIMES:x}],-1
            jne done
            mov ecx,dword ptr [0x{self.ELAPSED:x}]
            mov dword ptr [eax*4+0x{self.TIMES:x}],ecx
        done:
            popad
            popfd
            jmp 0x458e9e
        '''
        self.memory.write(self.MOWER_HOOK,self.asm(source,self.MOWER_HOOK))
        self.memory.write(hook,self.asm(f'jmp 0x{self.MOWER_HOOK:x}',hook)+b'\x90\x90')

    def draw_frame_source(self):
        # Original DrawDirtyStuff's semantic draw phase. DrawScreen includes
        # all widget/CT draw callbacks and locks the destination surface.
        # Redraw also flushes the renderer; omitting it leaks queued geometry.
        source='''
            push 0
            call 0x5a98b0
            add esp,4
            mov eax,dword ptr [0x6a9ec0]
            mov byte ptr [eax+0x458],1
            push dword ptr [eax+0x320]
            call 0x538eb0
            mov eax,dword ptr [0x6a9ec0]
            mov byte ptr [eax+0x458],0
            mov ecx,eax
            mov edx,dword ptr [ecx]
            push 0
            call dword ptr [edx+0x170]
            push 1
            call 0x5a98b0
            add esp,4
        '''
        if hasattr(self,'display_counter'):
            bind=f'''
            push dword ptr [0x6a9ec0]
            call dword ptr [0x{self.SHARED+0x80:x}]
            mov dword ptr [0x{self.SHARED+0x84:x}],eax
'''
            source=bind+source
        if not getattr(self,'present_frames',True):
            source=source.replace('''            mov ecx,eax
            mov edx,dword ptr [ecx]
            push 0
            call dword ptr [edx+0x170]
''','')
        return source

    def battle_steps(self,count,render=True):
        draw=self.draw_frame_source() if render else ''
        self.execute(f'''
            mov dword ptr [0x{self.SHARED+8:x}],{count}
        tick:
            inc dword ptr [0x{self.ELAPSED:x}]
            mov ecx,dword ptr [0x6a9ec0]
            call 0x{self.TRAMP:x}
            {draw}
            cmp dword ptr [0x7013a0],0
            je done
            dec dword ptr [0x{self.SHARED+8:x}]
            jnz tick
        done:
        ''')

    def mower_times(self):
        return list(struct.unpack('<5i',self.memory.read(self.TIMES,20)))

    def normal_frames(self,count):
        """Verification path: let the unmodified outer game loop run/draw."""
        self.memory.put32(self.SHARED+0x14,count)
        self.wait(lambda:self.memory.u32(self.SHARED+0x14)==0 and
                  self.memory.u32(self.SHARED+4)==1,60,'normal-frame comparison')

    def trace_rng(self):
        """Observe calls to the global MT, excluding private particle RNGs."""
        hook=0x5a9940
        if self.memory.read(hook,10)!=bytes.fromhex('81 ba c0 09 00 00 70 02 00 00'):
            raise RuntimeError('RNG probe hook mismatch')
        callback=self.BASE+0xa00
        self.RNG_COUNT=self.SHARED+0x20
        self.RNG_LOG=self.memory.alloc(0x200000)
        source=f'''
            pushfd
            pushad
            cmp edx,0x75a910
            jne done
            mov ebx,dword ptr [0x{self.RNG_COUNT:x}]
            cmp ebx,65536
            jae done
            mov edi,ebx
            shl edi,5
            add edi,0x{self.RNG_LOG:x}
            mov eax,dword ptr [0x{self.ELAPSED:x}]
            stosd
            mov eax,dword ptr [edx+0x9c0]
            stosd
            lea esi,[esp+36]
            mov ecx,5
            rep movsd dword ptr es:[edi],dword ptr [esi]
            mov eax,dword ptr [esp+16]
            stosd
            inc dword ptr [0x{self.RNG_COUNT:x}]
        done:
            popad
            popfd
            cmp dword ptr [edx+0x9c0],624
            jmp 0x5a994a
        '''
        self.memory.write(callback,self.asm(source,callback))
        self.memory.write(hook,self.asm(f'jmp 0x{callback:x}',hook)+b'\x90'*5)

    def rng_trace(self):
        count=self.memory.u32(self.RNG_COUNT)
        data=b''.join(self.memory.read(self.RNG_LOG+start,min(0x80000,count*32-start))
                      for start in range(0,count*32,0x80000))
        return list(struct.iter_unpack('<8I',data))

    def enter_survival(self,mode=1):
        if self.memory.u32(self.lawn+0x7fc)==0:
            raise RuntimeError('Original loading screen has not completed')
        self.execute(f'''
            mov esi,dword ptr [0x6a9ec0]
            call 0x44f9e0
            push 0
            push {mode}
            mov esi,dword ptr [0x6a9ec0]
            call 0x44f560
        ''')

    def steps(self,count,render=True):
        draw=self.draw_frame_source() if render else ''
        self.execute(f'''
            mov dword ptr [0x{self.SHARED+8:x}], {count}
        tick:
            mov ecx,dword ptr [0x6a9ec0]
            call 0x{self.TRAMP:x}
            {draw}
            dec dword ptr [0x{self.SHARED+8:x}]
            jnz tick
        ''')

    def release(self):
        self.memory.write(self.HOOK,self.original)
        self.memory.put32(self.SHARED,0xffffffff)
        self.memory.close()
