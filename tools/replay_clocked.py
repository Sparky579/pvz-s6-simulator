from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import trial
c=Config.parse({**json.loads(Path('examples/basic.json').read_text()),'max_frames':5000})
with GameProcess(log_dir=Path('artifacts/clocked-replay/logs')) as x:
 x.install_table();x.instrument_mowers();x.clock_audio()
 results=[]
 for i in range(2):
  r=trial(x,c,c.data['seed']);x.check_audio();results.append(r)
  print(i,r['frames'],r['speedup'],flush=True)
 Path('artifacts/clocked-replay/data.json').write_text(json.dumps(results,indent=2))
 for a,b in zip(results[0]['checkpoints'],results[1]['checkpoints']):print(a['frame'],a['digest']==b['digest'])
