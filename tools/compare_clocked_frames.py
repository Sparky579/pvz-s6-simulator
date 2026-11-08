from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare,state_data
c=Config.parse(json.loads(Path('examples/basic.json').read_text()))
with GameProcess(log_dir=Path('artifacts/frame-compare/logs')) as x:
 x.install_table();x.instrument_mowers();x.clock_audio()
 for i in range(3):prepare(x,c,c.data['seed'])
 fast=[state_data(x)]
 x.battle_steps(500);fast.append(state_data(x))
 prepare(x,c,c.data['seed']);normal=[state_data(x)]
 x.normal_frames(500);normal.append(state_data(x))
 Path('artifacts/frame-compare/clocked-data.json').write_text(json.dumps({'fast':fast,'normal':normal}))
 for tick,(left,right) in enumerate(zip(fast,normal)):
  x.check_audio();print('frame',tick*500)
  for name in left:
   if left[name]!=right[name]:
    print('DIFFERENT',name)
    if name=='rng':print('indices',left[name][-8:],right[name][-8:])
    else:
     for i,(a,b) in enumerate(zip(left[name],right[name])):
      if a!=b:print(i,[(j,v,w) for j,(v,w) in enumerate(zip(a,b)) if v!=w] if isinstance(a,list) else (a,b))
