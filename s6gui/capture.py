"""Original 800x600 frame capture (build/render_capture.dll) and background choice."""
from __future__ import annotations
import mmap
import os
from pathlib import Path
import struct
import subprocess
from .platform import ROOT, WINDOWS, game_path, shared_dir

WIDTH, HEIGHT = 800, 600
PIXELS = WIDTH*HEIGHT*4
STRIDE = PIXELS+8

# Board::DrawBackground (4162C2) picks an image global by background type, then
# continues at 416323. Overriding EBX there changes only the drawn picture.
# The 斗蛐蛐 maps are newimages slots 90..95 (CT 6114 reads [6ff168+n*4]).
SCENES = [('原模式背景', None)]+[(f'斗蛐蛐地图{n}', 0x6ff168+n*4) for n in range(6)]+[
    ('原版白天背景', 0x6a77c4), ('原版黑夜背景', 0x6a7b08), ('原版屋顶背景', 0x6a7724)]
SCENE_HOOK = 0x416323
SCENE_ORIGINAL = bytes.fromhex('8b 86 50 55 00 00')


def scene_names():
    return [name for name, _ in SCENES]


def set_scene(engine, name):
    address = dict(SCENES)[name]
    m = engine.memory
    current = m.read(SCENE_HOOK, 6)
    if not hasattr(engine, 'SCENE_CODE'):
        if current != SCENE_ORIGINAL:
            raise RuntimeError('Unexpected Board::DrawBackground bytes')
        engine.SCENE_CODE = engine.BASE+0xe000
    if address is None:
        m.write(SCENE_HOOK, SCENE_ORIGINAL)
        return
    if not m.u32(address):
        raise RuntimeError(f'{name} 图片未加载')
    code = engine.SCENE_CODE
    m.write(code, engine.asm(f'mov ebx,dword ptr [0x{address:x}];mov eax,dword ptr [esi+0x5550];'
                             f'jmp 0x416329', code))
    m.write(SCENE_HOOK, engine.asm(f'jmp 0x{code:x}', SCENE_HOOK)+b'\x90')


def capture_dll():
    dll = ROOT/'build/render_capture.dll'
    if not dll.exists():
        if WINDOWS:
            raise RuntimeError('缺少 build/render_capture.dll')
        compiler = ROOT/'.toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix'
        subprocess.run([str(compiler), '-O2', '-Wall', '-shared', '-static-libgcc',
                        '-Wl,--kill-at,--no-insert-timestamp', str(ROOT/'tools/render_capture.c'),
                        '-o', str(dll)], check=True)
    return dll


def load_library(e, dll, names, scratch, results):
    """LoadLibraryW + GetProcAddress inside the game; scratch gets 0x1000 bytes of strings."""
    e.memory.write(scratch, game_path(dll).encode('utf-16-le')+b'\0\0')
    cursor = scratch+0x600
    strings = {}
    for name in ('LoadLibraryW', 'kernel32.dll')+tuple(names):
        strings[name] = cursor
        data = name.encode()+b'\0'
        e.memory.write(cursor, data)
        cursor += len(data)
    e.execute(f'''
        push {strings['kernel32.dll']}
        call dword ptr [0x{e.api['GetModuleHandleA']:x}]
        push {strings['LoadLibraryW']}
        push eax
        call dword ptr [0x{e.api['GetProcAddress']:x}]
        push {scratch}
        call eax
        mov dword ptr [0x{results:x}],eax
    ''')
    module = e.memory.u32(results)
    if not module:
        raise RuntimeError(f'Cannot load {Path(dll).name}')
    functions = {}
    for i, name in enumerate(names):
        address = results+4+i*4
        e.execute(f'push {strings[name]};push {module};'
                  f'call dword ptr [0x{e.api["GetProcAddress"]:x}];'
                  f'mov dword ptr [0x{address:x}],eax')
        functions[name] = e.memory.u32(address)
        if not functions[name]:
            raise RuntimeError(f'Missing {Path(dll).name} function: {name}')
    return functions


class Capture:
    """Load the capture DLL into a prepared engine; same protocol as tools/render_match.py."""
    NAMES = ('CaptureInit', 'CaptureSelect', 'CaptureFrame', 'CaptureReset', 'CaptureClose')

    def __init__(self, engine, capacity, tag):
        self.e = e = engine
        self.capacity = capacity
        self.path = shared_dir()/f's6-gui-{tag}-{os.getpid()}.bin'
        if not hasattr(e, 'capture_functions'):
            e.capture_functions = load_library(e, capture_dll(), self.NAMES, e.BASE+0x10000, e.SHARED+0x100)
        self.f = e.capture_functions
        if not hasattr(e, 'FAST_DRAW'):
            # Creates the original-CT-only board draw stub CaptureSelect(0) uses.
            e.set_fast_drawing(True)
            e.set_fast_drawing(False)
        self.saved_counter = e.display_counter
        # CaptureSelect manages the destination vtable for every draw.
        del e.display_counter
        e.present_frames = False
        e.memory.write(e.BASE+0x10800, game_path(self.path).encode('utf-16-le')+b'\0\0')
        e.execute(f'push {e.FAST_DRAW};push {capacity};push {e.BASE+0x10800};push {e.lawn};'
                  f'call {self.f["CaptureInit"]};mov dword ptr [0x{e.SHARED+0x120:x}],eax')
        error = e.memory.u32(e.SHARED+0x120)
        if error:
            raise RuntimeError(f'Capture init: {error}')
        self.file = open(self.path, 'r+b')
        self.map = mmap.mmap(self.file.fileno(), 0)

    def tick_source(self, label, every=4, stop_when_ended=True):
        """Assembly for count ticks (count preloaded at SHARED+8): update, draw, capture each n-th."""
        e, f = self.e, self.f
        ended = (f'cmp dword ptr [0x7013a0],0\n jne {label}_select\n mov eax,1\n'
                 if stop_when_ended else '')
        finish = f'cmp dword ptr [0x7013a0],0\n je {label}_done\n' if stop_when_ended else ''
        return f'''
            call {f['CaptureReset']}
        {label}_tick:
            inc dword ptr [0x{e.ELAPSED:x}]
            mov ecx,dword ptr [0x6a9ec0]
            call 0x{e.TRAMP:x}
            mov eax,dword ptr [0x{e.ELAPSED:x}]
            and eax,{every-1}
            cmp eax,1
            sete al
            movzx eax,al
            {ended}
        {label}_select:
            mov dword ptr [0x{e.SHARED+0x124:x}],eax
            push eax
            call {f['CaptureSelect']}
            {e.draw_frame_source()}
            cmp dword ptr [0x{e.SHARED+0x124:x}],0
            je {label}_skip
            push dword ptr [0x{e.ELAPSED:x}]
            call {f['CaptureFrame']}
        {label}_skip:
            {finish}
            dec dword ptr [0x{e.SHARED+8:x}]
            jnz {label}_tick
        {label}_done:
        '''

    def still(self):
        """Capture the current board without advancing the game."""
        e, f = self.e, self.f
        e.execute(f'''
            call {f['CaptureReset']}
            push 1
            call {f['CaptureSelect']}
            {e.draw_frame_source()}
            push dword ptr [0x{e.ELAPSED:x}]
            call {f['CaptureFrame']}
            push 0
            call {f['CaptureSelect']}
        ''')
        frames = list(self.frames())
        if not frames:
            raise RuntimeError('No frame captured')
        return frames[-1][1]

    def frames(self):
        error, count, width, height, bpp = struct.unpack_from('<5I', self.map)
        if error:
            raise RuntimeError(f'Capture error {error}, dimensions {width}x{height}x{bpp}')
        for i in range(count):
            offset = 64+i*STRIDE
            yield struct.unpack_from('<I', self.map, offset)[0], self.map[offset+8:offset+8+PIXELS]

    def close(self):
        e = self.e
        try:
            e.execute(f'call {self.f["CaptureClose"]}')
        finally:
            e.display_counter = self.saved_counter
            self.map.close()
            self.file.close()
            try:
                self.path.unlink()
            except OSError:
                pass


def to_image(pixels):
    from PIL import Image
    return Image.frombytes('RGB', (WIDTH, HEIGHT), pixels, 'raw', 'BGRX')
