"""Compare the fast drawing prototype to the saved six-map native reference."""
from pathlib import Path
import fcntl,json,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.parallel import Host
from s6.process import GameProcess
from s6.runner import prepare,state_data
from s6.table import ROOT
from fast_drawing import install

out=ROOT/'artifacts/speed-investigation/six-map-validation';out.mkdir(parents=True,exist_ok=True)
cases=list(json.loads((ROOT/'tests/scenarios.json').read_text()).items())
report={}
def work(worker):
 results=[]
 for name,data in cases[worker::3]:
  c=Config.parse(data)
  with Host(ROOT/f'.workers-s6/worker-{worker:02d}',out/name/'logs') as host:
   with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=out/name/'logs') as e:
    e.install_table();e.instrument_mowers();e.clock_audio();e.discard_pixels()
    prepare(e,c,c.data['seed']);install(e)
    snapshots=[state_data(e)];frames=[0];started=time.monotonic()
    for _ in range(6):
     e.battle_steps(1000);e.check_audio();snapshots.append(state_data(e));frames.append(e.memory.u32(e.ELAPSED))
    reference=json.loads((ROOT/f'artifacts/compact-scenarios-6000/{name}/result.json').read_text())['runs'][0]
    result={'frames':frames,'snapshots':snapshots,'wall_seconds':time.monotonic()-started,
            'matches_reference':frames==reference['frames'] and snapshots==reference['snapshots']}
    (out/name/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(name,'same states:',result['matches_reference'],flush=True)
    results.append((name,result['matches_reference']))
 return results
with open(ROOT/'.workers-s6/.pool.lock','w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 with ThreadPoolExecutor(max_workers=3) as pool:
  for future in as_completed([pool.submit(work,i) for i in range(3)]):report.update(future.result())
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
if not all(report.values()):raise SystemExit('Fast drawing changed a reference state')
