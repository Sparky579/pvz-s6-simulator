"""Run every requested seed in a fresh game and preserve native failures."""
from pathlib import Path
import argparse,json,os,sys,time
from concurrent.futures import CancelledError
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
import s6.parallel as parallel
from s6.runner import manifest,trial

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('config',type=Path);p.add_argument('--workers',type=int,default=0)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--resume',action='store_true',help='Keep finished seeds and run only the original plan’s missing seeds')
p.add_argument('--lanes',type=int,nargs='+',default=[1,3,5],help='Lane observations counted in progress reports')
p.add_argument('--shards',type=int,default=1,help='Number of disjoint interleaved seed assignments')
p.add_argument('--shard-index',type=int,default=0,help='Zero-based assignment to execute on this machine')
p.add_argument('--record-matches',action='store_true',help='Save initial states, per-match replay files, and update matches.md/CSV after every game')
speed=p.add_mutually_exclusive_group()
speed.add_argument('--speed-mode',choices=('exact','fast'),help='Override the configuration speed mode')
speed.add_argument('--fast-drawing',action='store_true',help='Historical prototype; use --speed-mode fast for production runs')
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
data=json.loads(a.config.read_text())
if a.speed_mode is not None:data['speed_mode']=a.speed_mode
c=Config.parse(data)
if a.shards<1 or not 0<=a.shard_index<a.shards:raise ValueError('Invalid shard assignment')
if not a.lanes or len(set(a.lanes))!=len(a.lanes) or any(l not in range(1,6) for l in a.lanes):
    raise ValueError('Lanes must be unique values in 1..5')
assignment={'shards':a.shards,'shard_index':a.shard_index}
if a.fast_drawing and c.data['speed_mode']!='exact':
    raise ValueError('The historical prototype must not be combined with the production fast mode')
profile='original CT overlay only; no screen lock' if a.fast_drawing or c.data['speed_mode']=='fast' else 'original full draw'
execution_manifest=manifest(c.data['speed_mode'])
if a.resume:
    result=json.loads(a.output.read_text())
    if result['manifest']!=execution_manifest or result['config_sha256']!=c.digest:
        raise ValueError('Resume requires the exact original configuration and execution fingerprint')
    if result.get('drawing_profile','original full draw')!=profile:raise ValueError('Resume drawing profile differs')
    if result.get('assignment',{'shards':1,'shard_index':0})!=assignment:raise ValueError('Resume assignment differs')
else:
    if a.output.exists():raise ValueError('Output already exists; use --resume to preserve completed seeds')
    result={'manifest':execution_manifest,'config':c.data,'config_sha256':c.digest,'trials':[],
            'experiment_driver':'fresh game for every seed; original errors recorded without correction',
            'drawing_profile':profile,'assignment':assignment,'observed_lanes':a.lanes}
completed={((t['seed']-c.data['seed'])&0xffffffff):t for t in result['trials']}
if len(completed)!=len(result['trials']) or any(i>=c.data['repetitions'] for i in completed):
    raise ValueError('Resume input has duplicate or unplanned seeds')
assigned=[i for i in range(c.data['repetitions']) if i%a.shards==a.shard_index]
if any(i not in assigned for i in completed):raise ValueError('Result contains another shard’s seed')
pending=[i for i in assigned if i not in completed]
if not pending:
    print('All planned seeds already have results.');raise SystemExit(0)
schedule=Config.parse({**c.data,'repetitions':len(pending)})
if a.fast_drawing:
    from s6 import runner
    from fast_drawing import install
    original_prepare=runner.prepare
    def fast_prepare(engine,config,seed):
        original_prepare(engine,config,seed)
        install(engine)
    runner.prepare=fast_prepare

recorder=None
if a.record_matches:
    from s6 import runner
    from match_records import MatchRecorder,write_documents
    recorder=MatchRecorder(a.output.parent,c,execution_manifest)
    result['runtime_environment']=recorder.environment
    original_record_prepare=runner.prepare
    def record_prepare(engine,config,seed):
        initial=recorder.begin(seed)
        original_record_prepare(engine,config,seed)
        recorder.prepared(engine,seed,initial)
    runner.prepare=record_prepare


def observed_trial(engine,config,schedule_seed,cancel_event):
    seed=(c.data['seed']+pending[(schedule_seed-config.data['seed'])&0xffffffff])&0xffffffff
    started=time.monotonic()
    try:return trial(engine,c,seed,cancel_event)
    except CancelledError:raise
    except Exception as exc:
        # Observe what already happened. Never change the original animation,
        # CT logic, RNG, or mower events to force a failed trial to finish.
        result={'seed':seed,'status':'native_error','error':repr(exc),
                'frames':None,'mower_frames':[None]*5,'checkpoints':[],
                'wall_seconds':time.monotonic()-started,'game_seconds':None,'speedup':None}
        for name,read in [('frames',lambda:engine.memory.u32(engine.ELAPSED)),
                          ('mower_frames',engine.mower_times),
                          ('active_at_error',lambda:engine.memory.u32(0x7013a0)),
                          ('context',lambda:engine.memory.command('C'))]:
            try:result[name]=read()
            except Exception as read_error:result[name+'_read_error']=repr(read_error)
        result['mower_frames']=[v if v is not None and v>=0 else None for v in result['mower_frames']]
        if result['frames'] is not None:result['game_seconds']=result['frames']/100
        return result


parallel.trial=observed_trial


def save():
    temporary=a.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    os.replace(temporary,a.output)


def on_result(index,item):
    original_index=pending[index]
    if item['seed']!=(c.data['seed']+original_index)&0xffffffff:raise ValueError('Seed scheduling mismatch')
    if recorder:recorder.finish(item)
    completed[original_index]=item;result['trials']=[completed[i] for i in sorted(completed)]
    save()
    if recorder:write_documents(a.output.parent,result)
    observed=sum(t['mower_frames'][lane-1] is not None for t in completed.values()
                 if t.get('valid_for_statistics',True) for lane in a.lanes)
    print(f'{len(completed)}/{c.data["repetitions"]}: seed={item["seed"]}, '
          f'{item["status"]}, selected lane observations={observed}',flush=True)


save()
if recorder:write_documents(a.output.parent,result)
started=time.monotonic();initial_count=len(completed)
print(f'Starting {len(pending)} pending seeds; preserving {initial_count} finished seeds.',flush=True)
try:
    _,execution=parallel.run_batch(schedule,workers=a.workers,log_dir=a.output.parent/f'fresh-logs-from-{initial_count:03d}',
                                   on_result=on_result,reuse_game=False)
except KeyboardInterrupt:
    result.setdefault('segments',[]).append({'initial_count':initial_count,'final_count':len(completed),
        'wall_seconds':time.monotonic()-started,'requested_workers':a.workers,'interrupted':True})
    save();raise SystemExit('Saved completed seeds; --resume will restart only pending seeds.')
result['execution']={**execution,'scope':'last execution segment'}
result.setdefault('segments',[]).append({'initial_count':initial_count,'final_count':len(completed),**execution})
trials=result['trials']
result['summary']={'attempted_matches':len(trials),
                   'assigned_matches':len(assigned),
                   'completed_matches':sum(t['status']=='all_mowers_triggered' for t in trials),
                   'native_errors':sum(t['status']=='native_error' for t in trials),
                   'selected_lane_observations':sum(t['mower_frames'][lane-1] is not None for t in trials
                                                    if t.get('valid_for_statistics',True) for lane in a.lanes)}
save()
print(json.dumps(result['summary']),flush=True)
