"""Replay only native sound events, verifying gameplay against the saved match."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.parallel import clone_prefix
from s6.process import GameProcess
from s6.runner import manifest,prepare,state
from s6.table import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('replay',type=Path)
    p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--prefix',type=Path,required=True)
    p.add_argument('--preview-frames',type=int,default=0)
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    prior=json.loads(a.replay.read_text());reference=prior['trials'][0]
    if prior['manifest']!=manifest(prior['config'].get('speed_mode','exact')):
        raise ValueError('Replay source manifest differs')
    config=Config.parse({**prior['config'],'speed_mode':'fast'})
    expected={x['frame']:x['digest'] for x in reference['checkpoints']}
    clone_prefix(ROOT/'.wine-s6',a.prefix.resolve())
    dll=ROOT/'build/capture_sfx.dll'
    report={'source':str(a.replay.resolve()),'seed':reference['seed'],'checkpoints':[]}
    started=time.monotonic()
    with GameProcess(prefix=a.prefix,log_dir=a.output/'logs') as e:
        e.install_table(five_mowers=False);e.instrument_mowers()
        base=e.BASE+0x10000
        def wide(path):return ('Z:'+str(path.resolve()).replace('/','\\')).encode('utf-16-le')+b'\0\0'
        e.memory.write(base,wide(dll));e.memory.write(base+0x600,wide(a.output))
        names={};cursor=base+0x1200
        for name in ['kernel32.dll','LoadLibraryW','CaptureSfxInit','CaptureSfxBegin','CaptureSfxClose','S6AudioError','S6CaptureError']:
            names[name]=cursor;data=name.encode()+b'\0';e.memory.write(cursor,data);cursor+=len(data)
        e.execute(f'push {names["kernel32.dll"]};call dword ptr [{e.api["GetModuleHandleA"]}];'
                  f'push {names["LoadLibraryW"]};push eax;call dword ptr [{e.api["GetProcAddress"]}];'
                  f'push {base};call eax;mov dword ptr [{e.SHARED+0x100}],eax')
        module=e.memory.u32(e.SHARED+0x100)
        if not module:raise RuntimeError('Capture DLL did not load')
        functions={}
        for name in ['CaptureSfxInit','CaptureSfxBegin','CaptureSfxClose','S6AudioError','S6CaptureError']:
            e.execute(f'push {names[name]};push {module};call dword ptr [{e.api["GetProcAddress"]}];'
                      f'mov dword ptr [{e.SHARED+0x104}],eax')
            functions[name]=e.memory.u32(e.SHARED+0x104)
            if not functions[name]:raise RuntimeError(f'Missing capture symbol {name}')
        e.execute(f'push {base+0x600};push {e.lawn};call {functions["CaptureSfxInit"]};'
                  f'mov dword ptr [{e.SHARED+0x108}],eax')
        if e.memory.u32(e.SHARED+0x108):raise RuntimeError('Cannot initialize capture')
        e.audio_error=functions['S6AudioError']
        def check():
            e.check_audio();error=e.memory.u32(functions['S6CaptureError'])
            if error:raise RuntimeError(f'Native PCM capture error: {error:#x}')
        e.discard_pixels();prepare(e,config,reference['seed']);check()
        if state(e)!=expected[0]:raise ValueError('Initial gameplay state differs')
        e.execute(f'call {functions["CaptureSfxBegin"]}')
        while e.memory.u32(0x7013a0) and (not a.preview_frames or e.memory.u32(e.ELAPSED)<a.preview_frames):
            frame=e.memory.u32(e.ELAPSED)
            e.battle_steps(min(1000,a.preview_frames-frame) if a.preview_frames else 1000)
            check();frame=e.memory.u32(e.ELAPSED)
            if frame in expected:
                digest=state(e);matches=digest==expected[frame]
                report['checkpoints'].append({'frame':frame,'matches':matches,'digest':digest})
                if not matches:raise ValueError(f'Audio observer diverged at frame {frame}')
            if frame%10000==0:print(f'Captured {frame/100:.2f}s; checkpoints match',flush=True)
        report['ended']=e.memory.u32(0x7013a0)==0
        report['end_frame']=e.memory.u32(e.ELAPSED)
        report['mower_frames']=e.mower_times()
        if report['ended']:
            runner_up=sorted(reference['mower_frames'])[-2]
            if report['end_frame']!=runner_up or report['mower_frames']!=[t if t<=runner_up else -1 for t in reference['mower_frames']]:
                raise ValueError('Ending differs from rendered video')
            e.steps(300);check()
        e.execute(f'call {functions["CaptureSfxClose"]}');check()
    report['wall_seconds']=time.monotonic()-started
    report['captured_game_frames']=report['end_frame']+(300 if report['ended'] else 0)
    a.output.joinpath('capture.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f'Complete: {a.output}; {report["end_frame"]} frames, {report["wall_seconds"]:.1f}s',flush=True)


if __name__=='__main__':main()
