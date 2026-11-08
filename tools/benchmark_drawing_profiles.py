"""Synchronize four drawing profiles at the same native battle frame."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,os,sys,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.parallel import clone_prefix
from s6.runner import prepare,state_data
from s6.table import ROOT

out=ROOT/'artifacts/speed-investigation/drawing-ablation';out.mkdir(parents=True,exist_ok=True)
clone_prefix(ROOT/'.workers-s6/worker-13',ROOT/'.workers-s6/worker-12')
barrier=threading.Barrier(4)
data=json.loads((ROOT/'examples/ji_huo_lie_huo_xian_135.json').read_text())
data.update(seed=20261027,repetitions=1,speed_mode='exact');config=Config.parse(data)

def cpu(pid):
    value=(Path('/proc')/str(pid)/'stat').read_text()
    fields=value[value.rfind(')')+2:].split()
    return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')

def work(index,overlay,no_lock):
    name=f'overlay-{int(overlay)}-no-lock-{int(no_lock)}'
    owner=GameProcess(prefix=ROOT/f'.workers-s6/worker-{12+index:02d}',log_dir=out/name/'logs')
    with owner as e:
        e.install_table();e.instrument_mowers();e.clock_audio();e.discard_pixels()
        prepare(e,config,config.data['seed'])
        if overlay or no_lock:
            e.set_fast_drawing(True)
            if not overlay:e.memory.put32(0x656ca8+0x68,0x41acf0)
            if not no_lock:
                screen=e.memory.u32(e.memory.u32(e.lawn+0x320)+0x60)
                e.memory.put32(e.memory.u32(screen)+47*4,0x56ba70)
        for _ in range(90):e.battle_steps(1000)
        before=state_data(e)
        barrier.wait(timeout=300)
        initial_cpu=cpu(owner.game.pid);started=time.monotonic()
        e.battle_steps(10000)
        elapsed=time.monotonic()-started;used_cpu=cpu(owner.game.pid)-initial_cpu
        result={'profile':name,'wall_seconds':elapsed,'process_cpu_seconds':used_cpu,
                'before':before,'after':state_data(e)}
        (out/name/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(name,'wall',round(elapsed,3),'CPU',round(used_cpu,3),flush=True)
        return result

with ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(lambda args:work(*args),[(0,False,False),(1,False,True),(2,True,False),(3,True,True)]))
report={'states_equal':all(r['before']==results[0]['before'] and r['after']==results[0]['after'] for r in results),
        'results':[{k:v for k,v in r.items() if k not in ('before','after')} for r in results]}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
