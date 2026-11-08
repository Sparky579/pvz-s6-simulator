"""Compare the supplied CT's empty-formation failure in both native drivers."""
from pathlib import Path
import json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.parallel import Host
from s6.runner import prepare
from s6.table import ROOT
from native_observer import NativeObserver

out=ROOT/'artifacts/empty-formation';out.mkdir(parents=True,exist_ok=True)
c=Config.parse({'seed':1,'formation':[[None]*5 for _ in range(5)]})
results=[]
with Host(ROOT/'.wine-s6',out/'logs') as host:
 for normal in (False,True):
  name='normal' if normal else 'fast'
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=out/name) as e:
   e.install_table();e.instrument_mowers();e.clock_audio()
   if not normal:e.discard_pixels()
   observer=NativeObserver(e)
   prepare(e,c,1);e.memory.put32(observer.count,0)
   def observed_wait(predicate,timeout,what):
    deadline=time.monotonic()+timeout
    while not predicate():
     if observer.records():raise RuntimeError('Observed native exception')
     if time.monotonic()>deadline:raise TimeoutError(what)
     time.sleep(.005)
   e.wait=observed_wait
   error=None
   try:
    for _ in range(20):
     (e.normal_frames if normal else e.battle_steps)(1000)
     if not e.memory.u32(0x7013a0):break
   except (RuntimeError,TimeoutError) as exc:error=str(exc)
   records=observer.records()
   result={'name':name,'frame':e.memory.u32(e.ELAPSED),'error':error,'records':records,
           'locations':[{hex(p):observer.describe_address(p) for p in [r['eip']]+r['stack']
                         if observer.describe_address(p)} for r in records]}
   results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
   print(name,'frame',result['frame'],'error',error,
         'exception',[(hex(r['code']),hex(r['eip'])) for r in records],flush=True)
if len(results)!=2 or not all(r['records'] for r in results):
 raise SystemExit('Empty-formation failure not reproduced in both paths')
signature=lambda r:(r['frame'],[(v['code'],v['eip'],v['access'],v['address_accessed']) for v in r['records']])
if signature(results[0])!=signature(results[1]):raise SystemExit('Empty-formation failure differs')
print('Both original execution paths reproduce the same failure; no CT changes applied.')
