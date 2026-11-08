"""Differential native tests across every supported five-lane survival map."""
from pathlib import Path
import argparse,fcntl,json,sys,time,traceback
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.parallel import Host
from s6.process import GameProcess
from s6.runner import prepare,state_data,manifest
from s6.table import ROOT
from native_observer import NativeObserver

p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=2000)
p.add_argument('--workers',type=int,default=3);p.add_argument('--discard-pixels',action='store_true');p.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/scenarios')
a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
cases=json.loads((ROOT/'tests/scenarios.json').read_text());items=list(cases.items())
lock=open(ROOT/'.workers-s6/.pool.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
report={'manifest':manifest(),'frames':a.frames,'discard_fast_pixels':a.discard_pixels,'cases':{}}

def run_case(worker,case):
 name,data=case;directory=a.output_dir/name;directory.mkdir(exist_ok=True)
 c=Config.parse(data);result={'config':c.data,'runs':[]}
 with Host(ROOT/f'.workers-s6/worker-{worker:02d}',directory/'logs') as host:
  for normal in [False,True]:
   mode='normal' if normal else 'fast';snapshots=[];frames=[]
   with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=directory/'logs'/mode) as e:
    e.install_table();e.instrument_mowers();e.clock_audio();observer=NativeObserver(e)
    if a.discard_pixels and not normal:e.discard_pixels();e.present_frames=False
    original_wait=e.wait
    def observed_wait(predicate,timeout,what):
     def checked():
      records=observer.records()
      if records:
       result['exceptions']=records
       (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
       raise RuntimeError(f'Original exception in {name}/{mode}: {hex(records[-1]["eip"])}')
      return predicate()
     return original_wait(checked,timeout,what)
    e.wait=observed_wait
    prepare(e,c,c.data['seed'])
    if a.discard_pixels and not normal:e.discard_pixels()
    snapshots.append(state_data(e));frames.append(0)
    start=time.monotonic()
    for offset in range(0,a.frames,1000):
     (e.normal_frames if normal else e.battle_steps)(min(1000,a.frames-offset))
     e.check_audio();snapshots.append(state_data(e));frames.append(e.memory.u32(e.ELAPSED))
     if not e.memory.u32(0x7013a0):break
    result['runs'].append({'mode':mode,'wall_seconds':time.monotonic()-start,'frames':frames,'snapshots':snapshots})
   (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 result['equal']=all(result['runs'][0][k]==result['runs'][1][k] for k in ('frames','snapshots'))
 (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 return name,result

# Each worker processes a static slice; no prefix is used by two cases at once.
def work(worker):
 rows=[]
 for case in items[worker::a.workers]:
  try:rows.append(run_case(worker,case))
  except Exception as exc:
   name,_=case
   result={'equal':False,'error':str(exc),'traceback':traceback.format_exc()}
   (a.output_dir/name/'failure.json').write_text(json.dumps(result,indent=2)+'\n')
   rows.append((name,result))
 return rows
with ThreadPoolExecutor(max_workers=a.workers) as pool:
 for future in as_completed([pool.submit(work,i) for i in range(a.workers)]):
  for name,result in future.result():
   report['cases'][name]={'equal':result['equal'],'result':str((a.output_dir/name/'result.json').resolve()),'error':result.get('error')}
   (a.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
   print(name,'equal:',result['equal'],flush=True)
lock.close()
if not all(c['equal'] for c in report['cases'].values()):raise SystemExit('Native differential mismatch')
