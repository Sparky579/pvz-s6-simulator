"""Export a saved match as video (with original sound effects) by replaying it with original drawing.

Checkpoint digests and mower frames are compared with the saved match while
rendering; any divergence aborts the export instead of producing a video.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import time
from .capture import Capture, set_scene
from .platform import ROOT, Slot, ffmpeg, initialize

FPS = 25


class Cancelled(Exception):
    pass


def export(record, output, scene='原模式背景', to_last=False, tail_seconds=3.0,
           sounds=('plant',), progress=lambda frame, total: None, log=print, cancel=None):
    from s6.config import Config
    from s6.runner import manifest, prepare, state
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    reference = record['trials'][0]
    if reference.get('status') != 'all_mowers_triggered' or None in reference['mower_frames']:
        raise ValueError('只能导出五路都已结束的有效对局')
    if record['manifest'] != manifest(record['config'].get('speed_mode', 'exact')):
        raise ValueError('该记录的原包/执行器指纹与当前程序不同，无法严格复现')
    config = Config.parse({**record['config'], 'speed_mode': 'exact', 'repetitions': 1})
    expected = {x['frame']: x['digest'] for x in reference['checkpoints']}
    ordered = sorted(reference['mower_frames'])
    end_frame = ordered[-1] if to_last else ordered[-2]
    limit = end_frame+10
    tail = int(tail_seconds*100)
    encoded = output.with_name(output.stem+'.partial'+output.suffix)
    silent = output.with_name(output.stem+'.video'+output.suffix)
    sound_log = output.with_name(output.stem+'.sound.bin')
    audio = output.with_name(output.stem+'.sound.wav')
    logs = ROOT/'artifacts/gui/render-logs'
    encoder = None
    frames_written = 0
    started = time.monotonic()
    try:
        with Slot('render', logs) as slot, slot.game(logs) as e:
            log('原游戏已加载')
            # Without to_last, the original CT 6093 ending (<= 1 mower left) stops at the runner-up.
            initialize(e, config.data['version'], five_mowers=to_last)
            set_scene(e, scene)
            prepare(e, config, reference['seed'])
            if state(e) != expected[0]:
                raise ValueError('初始状态与保存的对局不一致')
            capture = Capture(e, 32, 'render')
            if sounds:
                from . import sound as effects
                effects.start(e, sound_log)
            try:
                encoder = subprocess.Popen([
                    ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size', '800x600',
                    '-framerate', str(FPS), '-i', 'pipe:0', '-an',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(encoded)],
                    stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

                def drain():
                    nonlocal frames_written
                    for _, pixels in capture.frames():
                        encoder.stdin.write(pixels)
                        frames_written += 1

                ended = False
                while e.memory.u32(e.ELAPSED) < limit and not ended:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    before = e.memory.u32(e.ELAPSED)
                    count = min(100-before % 100, limit-before)
                    e.execute(f'mov dword ptr [0x{e.SHARED+8:x}],{count}\n'+capture.tick_source('main'),
                              timeout=120)
                    e.check_audio()
                    frame = e.memory.u32(e.ELAPSED)
                    ended = e.memory.u32(0x7013a0) == 0
                    if frame in expected and not ended:
                        if state(e) != expected[frame]:
                            raise ValueError(f'渲染在第 {frame} 帧与保存的对局分叉')
                    drain()
                    progress(frame, end_frame)
                if not ended:
                    raise ValueError('原结束条件没有在预期时刻触发')
                times = e.mower_times()
                wanted = [t if t <= end_frame else -1 for t in reference['mower_frames']]
                if times != wanted:
                    raise ValueError(f'推车时刻与保存的对局不同：{times} != {wanted}')
                log(f'对局结束于 {frame/100:.2f} 秒，校验通过；渲染结尾 {tail_seconds:g} 秒')
                for offset in range(0, tail, 100):
                    count = min(100, tail-offset)
                    e.execute(f'mov dword ptr [0x{e.SHARED+8:x}],{count}\n'+
                              capture.tick_source('tail', stop_when_ended=False), timeout=120)
                    drain()
                if sounds:
                    effects.finish(e)
            finally:
                capture.close()
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError('ffmpeg 编码失败')
        if sounds:
            log('混合音效…')
            sources, events = effects.read_log(sound_log)
            sources, _ = effects.select(sources, set(sounds))
            # Video frame 0 shows battle frame 1 (frames with ELAPSED % 4 == 1 are captured).
            effects.write_wav(audio, effects.mix(sources, events, 1, frames_written/FPS))
            encoded.replace(silent)
            subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(silent),
                            '-i', str(audio), '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(encoded)],
                           check=True)
            log(f'音效：{len(events)} 条事件，混入 {len(sources)} 种采样（{"、".join(sounds)}）')
        encoded.replace(output)
        log(f'完成：{output}（{frames_written/FPS:.1f} 秒视频，用时 {time.monotonic()-started:.0f} 秒）')
        return output
    finally:
        if encoder is not None and encoder.poll() is None:
            try:
                encoder.stdin.close()
            except OSError:
                pass
            encoder.terminate()
            encoder.wait()
        for leftover in (encoded, silent, sound_log, audio):
            if leftover.exists():
                leftover.unlink()
