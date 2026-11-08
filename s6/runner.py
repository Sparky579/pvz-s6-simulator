from __future__ import annotations
import hashlib
import json
import struct
import time
from functools import cache
from concurrent.futures import CancelledError
from .config import Config
from .table import GAME, TABLE


def sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()


@cache
def manifest(speed_mode='exact'):
    if speed_mode not in ('exact','fast'):raise ValueError('Unknown speed mode')
    from .assets import verified_assets
    assets=verified_assets()
    implementation=hashlib.sha256()
    from .table import ROOT
    for p in sorted((ROOT/'s6').glob('*.py'))+sorted((ROOT/'native').glob('*.c')):
        implementation.update(p.name.encode()+b'\0'+p.read_bytes())
    return {**assets,'exe_sha256':sha256(GAME/'PlantsVsZombies.exe'),
            'ct_sha256':sha256(TABLE),'gdi42_sha256':sha256(GAME/'gdi42.dll'),
            'dllmain_sha256':sha256(GAME/'DllMain.dll'),
            'runner_sha256':implementation.hexdigest(),
            'audio_clock_sha256':sha256(ROOT/'build/audio_clock.dll'),
            'bridge_sha256':sha256(ROOT/'build/bridge.exe'),
            'null_display_sha256':sha256(ROOT/'build/null_display.dll'),
            'audio_clock':'original DirectSound sample buffers, LawnApp+0x484, 100 Hz',
            'audio_output':'virtual healthy DirectSound device; PCM output disabled',
            'initial_audio_state':'empty original Foley slots and sample history; channel cleanup timestamp 0',
            'audio_cleanup_clock':'original allocator GetTickCount call uses LawnApp+0x484 * 10 ms',
            'frame_driver':'original total update + original DrawScreen (including CT draw state changes)',
            'speed_mode':speed_mode,
            'board_drawing':'original full scene' if speed_mode=='exact' else
                            'original CT overlay every tick; native scene omitted',
            'graphics_mode':'original software display, 800 x 600',
            'display_output':'virtual final-screen raster sink; no physical presentation' if speed_mode=='exact' else
                             'virtual final screen without surface locking or physical presentation',
            'initial_clocks':{'LawnApp+0x838':0,'SexyAppBase+0x484':0},
            'win32_acp':936,'locale':'zh_CN.UTF-8','newimages_count':99,
            'rules':'S6正赛(bug寒).CT core 3562 + 5995; 6093 mower threshold 1 -> 0',
            'frame_rate':100,'version':'s6-bug'}


def state_data(engine):
    m=engine.memory;b=engine.board
    result={}
    # Stable gameplay fields, excluding process addresses and animation handles.
    specs={
        'plants':(0xac,0xb0,0x14c,0x141,
                  [8,12,0x1c,0x24,0x28,0x3c,0x40,0x44,0x50,0x54,0x58,0x5c,0x60,0x64,0x104,0x114,0x118,0x11c,0x120,0x124]),
        'zombies':(0x90,0x94,0x15c,0xec,
                   [8,12,0x1c,0x24,0x28,0x2c,0x30,0x34,0x60,0x64,0x68,0xac,0xb0,0xb4,0xc8,0xcc,0xd0,0xd4,0xdc,0xe0,0x114,0x120,0x12c,0x130,0x140]),
        'projectiles':(0xc8,0xcc,0x94,0x50,
                       [8,12,0x1c,0x24,0x28,0x2c,0x30,0x34,0x38,0x3c,0x40,0x44,0x48,0x54,0x58,0x5c,0x60]),
    }
    for name,(base_offset,count_offset,stride,dead_offset,fields) in specs.items():
        base=m.u32(b+base_offset);count=m.u32(b+count_offset)
        if count>100000:raise RuntimeError(f'Invalid {name} high-water mark: {count}')
        data=m.read(base,count*stride) if count else b''
        items=[]
        for i in range(count):
            obj=data[i*stride:(i+1)*stride]
            if obj[dead_offset]:continue
            items.append([struct.unpack_from('<I',obj,o)[0] for o in fields])
        result[name]=items
    # CT 1316 modifies sniper targets and the aim latch during drawing.
    # Track these explicitly rather than waiting for a later RNG divergence.
    plants=m.u32(b+0xac);plant_count=m.u32(b+0xb0)
    zombies=m.u32(b+0x90);zombie_count=m.u32(b+0x94)
    plant_data=m.read(plants,plant_count*0x14c) if plant_count else b''
    snipers=[]
    for i in range(plant_count):
        obj=plant_data[i*0x14c:(i+1)*0x14c]
        if obj[0x141] or struct.unpack_from('<I',obj,0x24)[0]!=0:continue
        pointer=struct.unpack_from('<I',obj,0xdc)[0]
        target=None
        if pointer:
            offset=pointer-zombies
            target=['zombie_slot',offset//0x15c] if 0<=offset<zombie_count*0x15c and offset%0x15c==0 else ['unresolved',pointer]
        snipers.append({'slot':i,'target':target,'aim_latch':obj[0xfb]})
    result['snipers']=snipers
    result['rng']=m.read(0x75a910,0x9c4).hex()
    result['mower_times']=engine.mower_times()
    return result


def state(engine):
    encoded=json.dumps(state_data(engine),sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepare(engine, config: Config, seed):
    d=config.data;m=engine.memory
    # Always construct the board and load resources through the full original
    # draw path, including between trials in a reused game process.
    engine.set_fast_drawing(False)
    if engine.board:
        engine.execute('mov edi,dword ptr [0x6a9ec0];call 0x44f380')
    engine.reset_foley()
    # Original dancer phase uses the application lifetime counter, independently
    # of the board RNG. Define both original clocks as initial conditions so
    # resource-loading time and worker assignment cannot change the phase.
    m.put32(engine.lawn+0x838,0)
    m.put32(engine.lawn+0x484,0)
    m.put32(m.u32(engine.lawn+0x4b4)+0x3090,0)
    m.write(0x700000,engine.global_baseline)
    m.put32(0x701ea0,int(d['easter']=='disabled'))
    m.put32(0x701ea4,int(d['easter']=='forced'))
    m.put32(0x701820,int(d['elite']=='forced'))
    m.put32(0x701200,d['elite_marker'])
    m.put32(0x701190,d['giant'])
    engine.seed(seed)
    engine.enter_survival(d['mode'])
    engine.steps(1000)
    engine.start_playing()
    engine.verify_images()
    engine.reset_mowers()
    for row,cells in enumerate(d['formation']):
        for col,layers in enumerate(cells):
            for plant in layers:engine.plant(row,col,plant['id'],plant['xp'])
    engine.check_audio()
    m.write(engine.TIMES,b'\xff'*20)
    m.put32(engine.ELAPSED,0)
    m.put32(0x7013a0,1)
    if d['speed_mode']=='fast':engine.set_fast_drawing(True)


def trial(engine,config: Config,seed=None,cancel_event=None):
    d=config.data;seed=d['seed'] if seed is None else seed
    prepare(engine,config,seed)
    checkpoints=[{'frame':0,'digest':state(engine)}]
    started=time.monotonic()
    while engine.memory.u32(engine.ELAPSED)<d['max_frames'] and engine.memory.u32(0x7013a0):
        if cancel_event is not None and cancel_event.is_set():raise CancelledError('Batch cancelled')
        frame=engine.memory.u32(engine.ELAPSED)
        engine.battle_steps(min(d['checkpoint_every'],d['max_frames']-frame))
        engine.check_audio()
        checkpoints.append({'frame':engine.memory.u32(engine.ELAPSED),'digest':state(engine)})
    duration=time.monotonic()-started
    frames=engine.memory.u32(engine.ELAPSED)
    times=engine.mower_times()
    ended=engine.memory.u32(0x7013a0)==0
    if ended and any(t<0 for t in times):
        raise RuntimeError(f'Ended without all five mower events: {times}')
    return {'seed':seed,'status':'all_mowers_triggered' if ended else 'frame_limit',
            'frames':frames,'game_seconds':frames/100,'wall_seconds':duration,
            'speedup':frames/100/duration if duration else None,
            'mower_frames':[t if t>=0 else None for t in times],
            'checkpoints':checkpoints}
