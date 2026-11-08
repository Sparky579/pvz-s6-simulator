"""Locate the first original global RNG divergence across fresh games."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.parallel import Host
from s6.config import Config
from s6.runner import prepare,state_data
from s6.table import ROOT
out=ROOT/'artifacts/fresh-trace';out.mkdir(exist_ok=True)
c=Config.parse({**json.loads((ROOT/'examples/basic.json').read_text()),'seed':20261027})
runs=[]
with Host(ROOT/'.workers-s6/worker-00',out/'logs') as host:
 for i in range(2):
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=out/'logs'/str(i)) as x:
   x.install_table();x.instrument_mowers();x.clock_audio();x.trace_rng();prepare(x,c,c.data['seed'])
   x.memory.put32(x.RNG_COUNT,0);snapshots=[state_data(x)]
   for j in range(10):x.battle_steps(500);x.check_audio();snapshots.append(state_data(x))
   runs.append({'snapshots':snapshots,'rng':x.rng_trace()});print('run',i,'calls',len(runs[-1]['rng']),flush=True)
   (out/'data.json').write_text(json.dumps(runs))
for i,(a,b) in enumerate(zip(runs[0]['snapshots'],runs[1]['snapshots'])):
 print(i*500,'equal',a==b,flush=True)
for i,(a,b) in enumerate(zip(runs[0]['rng'],runs[1]['rng'])):
 def key(v):return list(v[:2])+[n for n in v[2:7] if 0x400000<=n<0x652000]
 if key(a)!=key(b):
  print('first RNG divergence',i,flush=True)
  for r in runs:
   for v in r['rng'][max(0,i-3):i+5]:print(v[:2],[hex(z) for z in v[2:7]],flush=True)
  break
