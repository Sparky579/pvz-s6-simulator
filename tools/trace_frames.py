from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare,state_data
c=Config.parse(json.loads(Path('examples/basic.json').read_text()))
with GameProcess(log_dir=Path('artifacts/rng-trace/logs')) as x:
 x.install_table();x.instrument_mowers()
 for i in range(3):prepare(x,c,c.data['seed'])
 x.trace_rng();x.memory.put32(x.RNG_COUNT,0)
 x.battle_steps(500);fast=x.rng_trace()
 prepare(x,c,c.data['seed']);x.memory.put32(x.RNG_COUNT,0)
 x.normal_frames(500);normal=x.rng_trace()
 Path('artifacts/rng-trace/data.json').write_text(json.dumps({'fast':fast,'normal':normal}))
 print('RNG calls',len(fast),len(normal))
 for i,(a,b) in enumerate(zip(fast,normal)):
  if a[:2]!=b[:2] or [v for v in a[2:7] if 0x400000<=v<0x652000] != [v for v in b[2:7] if 0x400000<=v<0x652000]:
   print('first difference',i)
   for v in fast[max(0,i-3):i+6]:print('fast',v[:2],[hex(k) for k in v[2:7]])
   for v in normal[max(0,i-3):i+6]:print('normal',v[:2],[hex(k) for k in v[2:7]])
   break
