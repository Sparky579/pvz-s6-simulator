from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.parallel import Host
from s6.config import Config
from s6.runner import prepare,state_data
from s6.table import ROOT
out=ROOT/'artifacts/late-trace';out.mkdir(exist_ok=True)
c=Config.parse({**json.loads((ROOT/'examples/basic.json').read_text()),'seed':20261027})
runs=[]
for i in range(4):
 with Host(ROOT/f'.workers-s6/worker-{i%2:02d}',out/'logs'/str(i)) as host:
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=out/'logs'/str(i)) as x:
   x.install_table();x.instrument_mowers();x.clock_audio();prepare(x,c,c.data['seed'])
   x.battle_steps(4000);x.trace_rng();snapshots=[state_data(x)]
   for j in range(2):x.battle_steps(500);x.check_audio();snapshots.append(state_data(x))
   runs.append({'snapshots':snapshots,'rng':x.rng_trace()});print('run',i,'calls',len(runs[-1]['rng']),flush=True)
   (out/'data.json').write_text(json.dumps(runs))
for j,r in enumerate(runs[1:],1):
 print('comparison',j,flush=True)
 for i,(a,b) in enumerate(zip(runs[0]['snapshots'],r['snapshots'])):
  print(4000+i*500,'different fields',[k for k in a if a[k]!=b[k]],flush=True)
 for i,(a,b) in enumerate(zip(runs[0]['rng'],r['rng'])):
  def key(v):return list(v[:2])+[n for n in v[2:7] if 0x400000<=n<0x652000]
  if key(a)!=key(b):
   print('first RNG divergence',i,flush=True)
   for run in (runs[0],r):
    for v in run['rng'][max(0,i-3):i+5]:print(v[:2],[hex(z) for z in v[2:7]],flush=True)
   break
