from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare,state_data
c=Config.parse(json.loads(Path('examples/basic.json').read_text()))
with GameProcess(log_dir=Path('artifacts/state-probe/logs')) as x:
 x.install_table();x.instrument_mowers()
 snapshots=[]
 for i in range(4):
  prepare(x,c,c.data['seed']);s=state_data(x);snapshots.append(s)
  Path(f'artifacts/state-probe/{i}.json').write_text(json.dumps(s,indent=2))
 for name in snapshots[0]:
  a=snapshots[2][name];b=snapshots[3][name]
  if a!=b:
   print('DIFFERENT',name)
   if name=='rng':print(a[-16:],b[-16:])
   elif name=='plants':
    for i,(left,right) in enumerate(zip(a,b)):
     if left!=right:print(i,[(j,v,w) for j,(v,w) in enumerate(zip(left,right)) if v!=w])
   else:print(a,b)
