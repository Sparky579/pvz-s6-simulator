"""Render saved matches with the original CT runner-up ending and native pixels."""
from pathlib import Path
import argparse
import fcntl
import json
import mmap
import os
import queue
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.parallel import clone_prefix
from s6.process import GameProcess
from s6.runner import manifest, prepare, state, state_data
from s6.table import ROOT

WIDTH, HEIGHT, FPS = 800, 600, 25
PIXELS = WIDTH * HEIGHT * 4
STRIDE = PIXELS + 8


def winpath(path):
    return ('Z:' + str(path.resolve()).replace('/', '\\')).encode('utf-16-le') + b'\0\0'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('replay', type=Path)
    p.add_argument('-o', '--output', type=Path, required=True)
    p.add_argument('--preview-frames', type=int, default=0)
    p.add_argument('--tail-frames', type=int, default=300)
    p.add_argument('--prefix', type=Path, default=ROOT/'.wine-s6-render')
    p.add_argument('--start-frame', type=int, default=0)
    p.add_argument('--stop-frame', type=int, default=0)
    a = p.parse_args()
    a.output = a.output.resolve()
    out = a.output.parent
    out.mkdir(parents=True, exist_ok=True)
    output_lock = open(a.output.with_suffix('.lock'), 'w')
    fcntl.flock(output_lock, fcntl.LOCK_EX)
    verification = out/(a.output.stem+'.verification.json')
    if a.output.exists() and verification.exists() and not a.preview_frames:
        saved = json.loads(verification.read_text())
        if saved.get('source') == str(a.replay.resolve()) and (
                saved.get('ended') or a.stop_frame and saved.get('last_step_frame') == a.stop_frame):
            print(f'Already rendered and verified: {a.output}', flush=True)
            return
    prior = json.loads(a.replay.read_text())
    reference = prior['trials'][0]
    if prior['manifest'] != manifest(prior['config'].get('speed_mode', 'exact')):
        raise ValueError('Replay source manifest differs from this executor')
    config = Config.parse({**prior['config'], 'speed_mode': 'exact'})
    expected = {x['frame']: x['digest'] for x in reference['checkpoints']}
    runner_up = sorted(reference['mower_frames'])[-2]
    limit = a.stop_frame or a.preview_frames or runner_up + 10
    prefix = a.prefix.resolve()
    clone_prefix(ROOT / '.wine-s6', prefix)
    report = {'source': str(a.replay.resolve()), 'seed': reference['seed'],
              'end_rule': 'original CT 6093: remaining untriggered mowers <= 1',
              'runner_up_frame': runner_up, 'fps': FPS, 'checkpoints': [],
              'start_frame': a.start_frame,
              'audio': 'silent; original deterministic virtual sound device retained'}
    compiler = ROOT / '.toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix'
    dll = ROOT / 'build/render_capture.dll'
    if not dll.exists() or dll.stat().st_mtime < (ROOT/'tools/render_capture.c').stat().st_mtime:
        subprocess.run([str(compiler), '-O2', '-Wall', '-shared', '-static-libgcc',
                        '-Wl,--kill-at,--no-insert-timestamp', str(ROOT/'tools/render_capture.c'),
                        '-o', str(dll)], check=True)
    shared = Path('/dev/shm') / f's6-render-{os.getpid()}.bin'
    encoded = a.output.with_suffix('.partial.mp4')
    started = time.monotonic()
    encoder = None
    frame_count = 0
    try:
        with GameProcess(prefix=prefix, log_dir=out/'logs') as e:
            print('Original game loaded', flush=True)
            e.install_table(five_mowers=False)
            e.instrument_mowers()
            e.clock_audio()
            e.discard_pixels()
            prepare(e, config, reference['seed'])
            if state(e) != expected[0]:
                raise ValueError('Initial state differs from saved match')
            e.set_fast_drawing(True)
            while e.memory.u32(e.ELAPSED) < a.start_frame:
                before = e.memory.u32(e.ELAPSED)
                e.battle_steps(min(1000-before%1000, a.start_frame-before))
                frame = e.memory.u32(e.ELAPSED)
                if frame in expected and state(e) != expected[frame]:
                    raise ValueError(f'Fast-forward diverged at frame {frame}')
                if not e.memory.u32(0x7013a0):
                    raise ValueError('Match ended during fast-forward')
            print(f'Capture begins at frame {a.start_frame}', flush=True)
            e.set_fast_drawing(False)
            # CaptureSelect manages the destination vtable for every draw.
            del e.display_counter
            e.present_frames = False
            strings = e.BASE + 0x10000
            e.memory.write(strings, winpath(dll))
            e.memory.write(strings+0x600, winpath(shared))
            cursor = strings+0x1200
            names = {}
            for name in ('LoadLibraryW', 'kernel32.dll', 'CaptureInit', 'CaptureSelect',
                         'CaptureFrame', 'CaptureReset', 'CaptureClose'):
                names[name] = cursor
                data = name.encode()+b'\0'
                e.memory.write(cursor, data)
                cursor += len(data)
            e.execute(f'''
                push {names['kernel32.dll']}
                call dword ptr [0x{e.api['GetModuleHandleA']:x}]
                push {names['LoadLibraryW']}
                push eax
                call dword ptr [0x{e.api['GetProcAddress']:x}]
                push {strings}
                call eax
                mov dword ptr [0x{e.SHARED+0x100:x}],eax
            ''')
            module = e.memory.u32(e.SHARED+0x100)
            if not module:
                raise RuntimeError('Cannot load capture DLL')
            functions = {}
            for i, name in enumerate(('CaptureInit', 'CaptureSelect', 'CaptureFrame',
                                      'CaptureReset', 'CaptureClose')):
                address = e.SHARED+0x104+i*4
                e.execute(f'push {names[name]};push {module};'
                          f'call dword ptr [0x{e.api["GetProcAddress"]:x}];'
                          f'mov dword ptr [0x{address:x}],eax')
                functions[name] = e.memory.u32(address)
                if not functions[name]:
                    raise RuntimeError(f'Missing capture function: {name}')
            e.execute(f'push {e.FAST_DRAW};push 32;push {strings+0x600};push {e.lawn};'
                      f'call {functions["CaptureInit"]};'
                      f'mov dword ptr [0x{e.SHARED+0x120:x}],eax')
            error = e.memory.u32(e.SHARED+0x120)
            if error:
                raise RuntimeError(f'Capture init: {error}')
            encoder_log = open(out/(a.output.stem+'.ffmpeg.log'), 'w')
            encoder = subprocess.Popen([
                'ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y',
                '-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size', '800x600',
                '-framerate', str(FPS), '-i', 'pipe:0', '-an',
                '-c:v', 'libx264', '-threads', '3', '-preset', 'veryfast', '-crf', '20',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(encoded)
            ], stdin=subprocess.PIPE, stderr=encoder_log)
            pending = queue.Queue(maxsize=1)
            writer_errors = []
            def encode_frames():
                try:
                    while True:
                        frames = pending.get()
                        if frames is None:
                            break
                        for pixels in frames:
                            encoder.stdin.write(pixels)
                except BaseException as error:
                    writer_errors.append(error)
                finally:
                    encoder.stdin.close()
            writer = threading.Thread(target=encode_frames, daemon=True)
            writer.start()
            def submit(frames):
                while True:
                    if writer_errors:
                        raise writer_errors[0]
                    try:
                        pending.put(frames, timeout=.5)
                        return
                    except queue.Full:
                        pass
            with open(shared, 'r+b') as f, mmap.mmap(f.fileno(), 0) as capture:
                draw = e.draw_frame_source()
                def drain():
                    nonlocal frame_count
                    error, count, width, height, bpp = struct.unpack_from('<5I', capture)
                    if error:
                        raise RuntimeError(f'Capture error {error}, dimensions {width}x{height}x{bpp}')
                    frames = []
                    for i in range(count):
                        offset = 64+i*STRIDE
                        frame = struct.unpack_from('<I', capture, offset)[0]
                        pixels = capture[offset+8:offset+8+PIXELS]
                        if frame_count == 0:
                            from PIL import Image
                            Image.frombytes('RGB', (WIDTH,HEIGHT), pixels, 'raw', 'BGRX').save(out/(a.output.stem+'.first.png'))
                        frames.append(pixels)
                        frame_count += 1
                    submit(frames)
                    if count:
                        report['last_captured_frame'] = frame
                        if frame % 1000 == 997 or e.memory.u32(0x7013a0) == 0:
                            from PIL import Image
                            Image.frombytes('RGB', (WIDTH,HEIGHT), pixels, 'raw', 'BGRX').save(out/(a.output.stem+'.last.png'))

                # The first visible frame is the first update, preserving the
                # saved frame-zero state (drawing alone can alter CT fields).
                ended = False
                while e.memory.u32(e.ELAPSED) < limit and not ended:
                    before = e.memory.u32(e.ELAPSED)
                    count = min(100-before%100, limit-before)
                    e.execute(f'''
                        call {functions['CaptureReset']}
                        mov dword ptr [0x{e.SHARED+8:x}],{count}
                    tick:
                        inc dword ptr [0x{e.ELAPSED:x}]
                        mov ecx,dword ptr [0x6a9ec0]
                        call 0x{e.TRAMP:x}
                        mov eax,dword ptr [0x{e.ELAPSED:x}]
                        and eax,3
                        cmp eax,1
                        sete al
                        movzx eax,al
                        cmp dword ptr [0x7013a0],0
                        jne selected
                        mov eax,1
                    selected:
                        mov dword ptr [0x{e.SHARED+0x124:x}],eax
                        push eax
                        call {functions['CaptureSelect']}
                        {draw}
                        cmp dword ptr [0x{e.SHARED+0x124:x}],0
                        je no_capture
                        push dword ptr [0x{e.ELAPSED:x}]
                        call {functions['CaptureFrame']}
                    no_capture:
                        cmp dword ptr [0x7013a0],0
                        je done
                        dec dword ptr [0x{e.SHARED+8:x}]
                        jnz tick
                    done:
                    ''', timeout=120)
                    e.check_audio()
                    frame = e.memory.u32(e.ELAPSED)
                    ended = e.memory.u32(0x7013a0) == 0
                    if frame in expected and not ended:
                        digest = state(e)
                        matches = digest == expected[frame]
                        report['checkpoints'].append({'frame': frame, 'matches': matches, 'digest': digest})
                        if not matches:
                            raise ValueError(f'Render diverged from saved match at frame {frame}')
                    drain()
                    if frame % 5000 == 0 or ended or frame == limit:
                        print(f'Rendered {frame/100:.2f}/{runner_up/100:.2f} game seconds; '
                              f'{time.monotonic()-started:.1f}s elapsed; checkpoints match', flush=True)
                    if ended:
                        report['end_frame'] = frame
                        report['mower_frames'] = e.mower_times()
                        report['end_state'] = state_data(e)
                        expected_times = [t if t <= runner_up else -1 for t in reference['mower_frames']]
                        if report['mower_frames'] != expected_times:
                            raise ValueError('Mower events differ from saved match')
                        for offset in range(0, a.tail_frames, 100):
                            count = min(100, a.tail_frames-offset)
                            e.execute(f'''
                                call {functions['CaptureReset']}
                                mov dword ptr [0x{e.SHARED+8:x}],{count}
                            tail:
                                inc dword ptr [0x{e.ELAPSED:x}]
                                mov ecx,dword ptr [0x6a9ec0]
                                call 0x{e.TRAMP:x}
                                mov eax,dword ptr [0x{e.ELAPSED:x}]
                                and eax,3
                                cmp eax,1
                                sete al
                                movzx eax,al
                                mov dword ptr [0x{e.SHARED+0x124:x}],eax
                                push eax
                                call {functions['CaptureSelect']}
                                {draw}
                                cmp dword ptr [0x{e.SHARED+0x124:x}],0
                                je tail_skip
                                push dword ptr [0x{e.ELAPSED:x}]
                                call {functions['CaptureFrame']}
                            tail_skip:
                                dec dword ptr [0x{e.SHARED+8:x}]
                                jnz tail
                            ''', timeout=120)
                            drain()
                        report['tail_frames'] = a.tail_frames
                        report['tail_state'] = state_data(e)
                e.execute(f'call {functions["CaptureClose"]}')
                report['ended'] = ended
                report['last_step_frame'] = e.memory.u32(e.ELAPSED)
            submit(None)
            writer.join()
            if writer_errors:
                raise writer_errors[0]
            if encoder.wait() != 0:
                raise RuntimeError('FFmpeg failed; see encoder log')
            encoder_log.close()
        if not a.preview_frames and not a.stop_frame and not report['ended']:
            raise ValueError('Original runner-up ending did not trigger')
        encoded.replace(a.output)
        report['video_frames'] = frame_count
        report['duration_seconds'] = frame_count/FPS
        report['wall_seconds'] = time.monotonic()-started
        report['output'] = str(a.output)
        out.joinpath(a.output.stem+'.verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(f'Complete: {a.output} ({frame_count/FPS:.2f}s, {a.output.stat().st_size/1024/1024:.1f} MiB)', flush=True)
    finally:
        if encoder is not None and encoder.poll() is None:
            encoder.stdin.close()
            encoder.terminate()
            encoder.wait()
        shared.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
