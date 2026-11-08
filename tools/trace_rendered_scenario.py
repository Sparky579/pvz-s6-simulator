from pathlib import Path
import argparse,json,sys,struct,bisect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.parallel import Host
from s6.config import Config
from s6.runner import prepare,state_data
from s6.table import ROOT
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=Path('artifacts/hard-day-upgrades.json'));p.add_argument('--frames',type=int,default=1000)
p.add_argument('--output',type=Path,default=Path('artifacts/rendered-hard-day/data.json'));a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
c=Config.parse(json.loads(a.config.read_text()));runs=[]
with Host(ROOT/'.wine-s6',a.output.parent/'logs') as host:
 for normal in [False,True]:
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=a.output.parent/'logs'/str(normal)) as e:
   e.install_table();e.instrument_mowers();e.clock_audio();e.trace_rng();prepare(e,c,c.data['seed'])
   intervals=sorted((start,start+len(data),entry) for entry,p in e.programs for start,data in p.writes)
   starts=[x[0] for x in intervals]
   snapshots=[state_data(e)];trace=[];fpu=[]
   def floating():
    e.execute(f'fnstcw word ptr [0x{e.SHARED+0x54:x}];stmxcsr dword ptr [0x{e.SHARED+0x58:x}]')
    return e.memory.read(e.SHARED+0x54,8).hex()
   fpu.append(floating())
   for offset in range(0,a.frames,100):
    e.memory.put32(e.RNG_COUNT,0)
    (e.normal_frames if normal else lambda count:e.battle_steps(count,render=True))(min(100,a.frames-offset))
    records=e.rng_trace()
    if len(records)>=65536:raise RuntimeError('Trace overflow')
    def canonical(value):
     if 0x400000<=value<0x652000:return hex(value)
     i=bisect.bisect_right(starts,value)-1
     if i>=0 and value<intervals[i][1]:
      start,end,entry=intervals[i];return f'CT {entry}+{value-start:x}'
     return None
    trace.extend([list(r[:2])+[canonical(n) for n in r[2:7]] for r in records])
    snapshots.append(state_data(e));fpu.append(floating())
   runs.append({'snapshots':snapshots,'fpu':fpu,'rng':trace});a.output.write_text(json.dumps(runs));print('run normal',normal,'calls',len(trace),'fpu',fpu,flush=True)
for j,(left,right) in enumerate(zip(runs[0]['snapshots'],runs[1]['snapshots'])):print(j*100,[k for k in left if left[k]!=right[k]],flush=True)
for j,(left,right) in enumerate(zip(runs[0]['rng'],runs[1]['rng'])):
 if left!=right:
  print('first RNG difference',j,flush=True)
  for r in runs:
   for item in r['rng'][max(0,j-4):j+6]:print(item,flush=True)
  break
