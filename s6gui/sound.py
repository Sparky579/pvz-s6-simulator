"""Sound effects for exported videos.

build/sound_log.dll records every original DSoundInstance::Play plus later
stop/volume/pan/pitch/position changes, stamped with the battle frame, and the
PCM of each source sample the first time it is used. The mix is then rebuilt
offline at 100 frames per second of game time. Music (BASS) is not included.
"""
from __future__ import annotations
from pathlib import Path
import struct
import subprocess
import wave
from .capture import load_library
from .platform import ROOT, WINDOWS, game_path

RATE = 44100
MASTER = 0.8
PLAY, STOP, VOLUME, PAN, FREQUENCY, POSITION, SOURCE = range(1, 8)
NAMES = ('SoundLogStart', 'SoundLogFinish')


def library():
    dll = ROOT/'build/sound_log.dll'
    if not dll.exists():
        if WINDOWS:
            raise RuntimeError('缺少 build/sound_log.dll')
        compiler = ROOT/'.toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix'
        subprocess.run([str(compiler), '-O2', '-Wall', '-shared', '-static-libgcc',
                        '-Wl,--kill-at,--no-insert-timestamp', str(ROOT/'s6gui/native/sound_log.c'),
                        '-o', str(dll)], check=True)
    return dll


def start(e, path):
    if not hasattr(e, 'sound_functions'):
        e.sound_functions = load_library(e, library(), NAMES, e.BASE+0x11000, e.SHARED+0x140)
    e.memory.write(e.BASE+0x12000, game_path(path).encode('utf-16-le')+b'\0\0')
    e.execute(f'push {e.ELAPSED};push {e.BASE+0x12000};call {e.sound_functions["SoundLogStart"]};'
              f'mov dword ptr [0x{e.SHARED+0x14c:x}],eax')
    error = e.memory.u32(e.SHARED+0x14c)
    if error:
        raise RuntimeError(f'Sound log start: {error}')


def finish(e):
    e.execute(f'call {e.sound_functions["SoundLogFinish"]};mov dword ptr [0x{e.SHARED+0x14c:x}],eax')
    error = e.memory.u32(e.SHARED+0x14c)
    if error:
        raise RuntimeError(f'Sound log error: {error}')


def read_log(path):
    import numpy as np
    data = Path(path).read_bytes()
    sources, events = {}, []
    offset = 0
    while offset+32 <= len(data):
        kind, tick, obj, src, a, b, c, d = struct.unpack_from('<8I', data, offset)
        offset += 32
        if kind == SOURCE:
            raw = data[offset:offset+a]
            offset += a
            if not a or c == 0:
                continue
            if d == 16:
                pcm = np.frombuffer(raw, '<i2').astype(np.float32)/32768
            elif d == 8:
                pcm = (np.frombuffer(raw, np.uint8).astype(np.float32)-128)/128
            else:
                continue
            frames = pcm.reshape(-1, b)
            stereo = frames[:, :2] if b > 1 else np.repeat(frames, 2, 1)
            sources[src] = (stereo, c, b*d//8)
        else:
            events.append((kind, tick, obj, src, a, b, c, d))
    return sources, events


def gains(volume, pan):
    """DirectSound attenuation (hundredths of dB) -> left/right amplitude."""
    volume = struct.unpack('<i', struct.pack('<I', volume))[0]
    pan = struct.unpack('<i', struct.pack('<I', pan))[0]
    base = 10**(min(0, volume)/2000)
    left = base*(10**(-pan/2000) if pan > 0 else 1)
    right = base*(10**(pan/2000) if pan < 0 else 1)
    return left, right


def mix(sources, events, first_tick, seconds):
    """Stereo int16 samples; output time 0 is battle frame first_tick."""
    import numpy as np
    total = int(round(seconds*RATE))
    out = np.zeros((total, 2), np.float32)
    voices = {}

    def render(v, until):
        if not v.get('playing') or v['src'] not in sources:
            v['tick'] = until
            return
        pcm, source_rate, _ = sources[v['src']]
        start = round((v['tick']-first_tick)*RATE/100)
        stop = min(total, round((until-first_tick)*RATE/100))
        if stop <= max(start, 0):
            v['tick'] = until
            return
        n = stop-start
        step = (v['frequency'] or source_rate)/RATE
        positions = v['position']+step*np.arange(n)
        length = len(pcm)
        if v['looping']:
            positions %= length
        else:
            keep = positions < length-1
            if not keep.all():
                n = int(keep.sum())
                positions = positions[:n]
                v['playing'] = False
        index = positions.astype(np.int64)
        frac = (positions-index)[:, None]
        following = np.minimum(index+1, length-1)
        samples = pcm[index]*(1-frac)+pcm[following]*frac
        left, right = gains(v['volume'], v['pan'])
        samples *= np.array([left, right], np.float32)
        begin = start
        if begin < 0:
            samples = samples[-begin:]
            begin = 0
        out[begin:begin+len(samples)] += samples[:total-begin]
        v['position'] = (v['position']+step*(stop-start)) % length if v['looping'] else \
            v['position']+step*(stop-start)
        v['tick'] = until

    for kind, tick, obj, src, a, b, c, d in events:
        v = voices.setdefault(obj, {'playing': False, 'tick': tick, 'volume': 0, 'pan': 0,
                                    'frequency': 0, 'position': 0.0, 'looping': False, 'src': None})
        render(v, tick)
        if kind == PLAY:
            v.update(playing=True, src=src, looping=bool(a), volume=b, pan=c, frequency=d, position=0.0)
        elif kind == STOP:
            v['playing'] = False
        elif kind == VOLUME:
            v['volume'] = a
        elif kind == PAN:
            v['pan'] = a
        elif kind == FREQUENCY:
            v['frequency'] = a
        elif kind == POSITION and v['src'] in sources:
            v['position'] = float(a//sources[v['src']][2])
    end = first_tick+seconds*100
    for v in voices.values():
        render(v, end)
    np.clip(out*MASTER, -1, 1, out=out)
    return (out*32767).astype('<i2')


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


# Zombie voices/actions plus wave/UI cues; everything else in a battle is plant-side.
ZOMBIE = {
    'awooga', 'ballooninflate', 'balloon_pop', 'basketball', 'bossboulderattack', 'bossexplosion',
    'bungee_scream', 'bungee_scream2', 'bungee_scream3', 'chomp', 'chomp2', 'chompsoft', 'dancer',
    'digger_zombie', 'dirt_rise', 'dolphin_appears', 'dolphin_before_jumping', 'gargantuar_thump',
    'gargantudeath', 'groan', 'groan2', 'groan3', 'groan4', 'groan5', 'groan6', 'lowgroan', 'lowgroan2',
    'hydraulic', 'hydraulic_short', 'imp', 'imp2', 'jackinthebox', 'jack_surprise', 'jack_surprise2',
    'ladder_zombie', 'limbs_pop', 'newspaper_rarrgh', 'newspaper_rarrgh2', 'newspaper_rip', 'pogo_zombie',
    'polevault', 'RVthrow', 'scream', 'sukhbir', 'sukhbir2', 'sukhbir3', 'sukhbir4', 'sukhbir5', 'sukhbir6',
    'yuck', 'yuck2', 'zamboni', 'zombaquarium_die', 'zombie_entering_water', 'zombie_falling_1',
    'zombie_falling_2', 'zombiesplash', 'ZombiesOnYourLawn', 'evillaugh', 'hugewave', 'finalwave', 'siren',
    'losemusic', 'winmusic', 'finalfanfare', 'buttonclick', 'pause', 'gravebutton', 'loadingbar_zombie',
    'loadingbar_flower', 'readysetplant', 'roll_in', 'grassstep', 'bleep', 'buzzer',
}
MOWER = {'lawnmower', 'pool_cleaner'}


def category(name):
    stem = name.rsplit('.', 1)[0]
    return 'zombie' if stem in ZOMBIE else 'mower' if stem in MOWER else 'plant'


def identify(sources):
    """{source: file name or None}, by sample rate and length; PCM decides when categories differ."""
    import json
    import numpy as np
    from .platform import ffmpeg
    from s6.table import GAME
    table = json.loads((ROOT/'s6gui/sound_table.json').read_text(encoding='utf-8'))
    names = {}
    for src, (pcm, rate, _) in sources.items():
        candidates = [n for n, (r, frames) in table.items() if r == rate and abs(frames-len(pcm)) <= 64]
        if len({category(n) for n in candidates}) > 1:
            def distance(name):
                raw = subprocess.run([ffmpeg(), '-v', 'error', '-i', str(GAME/'sounds'/name),
                                      '-f', 's16le', '-ac', '2', '-'], capture_output=True).stdout
                other = np.frombuffer(raw, '<i2').reshape(-1, 2).astype(np.float32)/32768
                m = min(len(other), len(pcm))
                return float(np.abs(other[:m]-pcm[:m]).mean()) if m else 1.0
            candidates = [min(candidates, key=distance)]
        names[src] = candidates[0] if candidates else None
    return names


def select(sources, include):
    """Keep sources whose category is in include ('plant', 'mower', 'zombie'); unknown ones count as plant."""
    names = identify(sources)
    return {src: value for src, value in sources.items()
            if category(names[src] or 'unknown') in include}, names
