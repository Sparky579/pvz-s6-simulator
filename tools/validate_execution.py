"""Compare independent native runs, peripheral output, and outer-loop updates."""
from pathlib import Path
import argparse,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.parallel import Host
from s6.runner import prepare,state_data,manifest
from s6.table import ROOT

p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=5000)
p.add_argument('--normal',action='store_true');p.add_argument('--discard-pixels',action='store_true');p.add_argument('--skip-present',action='store_true');p.add_argument('--software',action='store_true');p.add_argument('--config',type=Path,default=ROOT/'examples/basic.json');p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
c=Config.parse(json.loads(a.config.read_text()))
runs=[];data={'manifest':manifest(),'frames':a.frames,'discard_fast_pixels':a.discard_pixels,'software_display':a.software,'skip_fast_present':a.skip_present,'runs':runs}
with Host(ROOT/'.wine-s6',a.output.parent/'logs') as host:
 for name,physical,normal in [('virtual-fast',False,False),('physical-fast',True,False)]+([('virtual-normal',False,True)] if a.normal else []):
  started=time.monotonic()
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,software_display=a.software,log_dir=a.output.parent/'logs'/name) as e:
   e.install_table();e.instrument_mowers();e.clock_audio(physical_output=physical)
   if a.discard_pixels and not normal:e.discard_pixels()
   if a.skip_present and not normal:
    if e.display_3d:raise ValueError('Skipping presentation requires the original software renderer')
    e.present_frames=False
   prepare(e,c,c.data['seed'])
   if a.discard_pixels and not normal:
    manager=e.memory.u32(e.lawn+0x320);image=e.memory.u32(manager+0x60)
    print('display after prepare',hex(image),hex(e.memory.u32(image)),'calls',e.memory.u32(e.display_counter),flush=True)
    e.discard_pixels()
    e.present_frames=not a.skip_present
   snapshots=[state_data(e)]
   battle=time.monotonic()
   for count in range(0,a.frames,1000):
    try:(e.normal_frames if normal else e.battle_steps)(min(1000,a.frames-count))
    except TimeoutError:
     print('native stall',e.memory.command('C'),'elapsed',e.memory.u32(e.ELAPSED),'normal remaining',e.memory.u32(e.SHARED+0x14),flush=True)
     raise
    e.check_audio();snapshots.append(state_data(e))
   elapsed=time.monotonic()-battle
   runs.append({'name':name,'battle_wall_seconds':elapsed,'total_wall_seconds':time.monotonic()-started,'snapshots':snapshots})
   print(name,round(elapsed,3),'seconds',flush=True)
  data['snapshots_equal']=all(r['snapshots']==runs[0]['snapshots'] for r in runs)
  a.output.write_text(json.dumps(data,indent=2)+'\n')
print('all snapshots equal:',data['snapshots_equal'],flush=True)
if not data['snapshots_equal']:raise SystemExit(1)
