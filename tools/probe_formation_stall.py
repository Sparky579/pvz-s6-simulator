"""Observe a problematic formation seed in a fresh original game process."""
from pathlib import Path
import argparse,json,re,struct,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import trial,state_data,prepare

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('config',type=Path);p.add_argument('--seed',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--normal',action='store_true')
p.add_argument('--max-frames',type=int)
p.add_argument('--four-mowers',action='store_true',help='Keep the supplied CT original four-mower end threshold')
p.add_argument('--prefix',type=Path)
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
d=json.loads(a.config.read_text());d.update(seed=a.seed,repetitions=1);c=Config.parse(d)
if a.max_frames:d['max_frames']=a.max_frames;c=Config.parse(d)
owner=GameProcess(prefix=a.prefix,log_dir=a.output.parent/'logs')
with owner as e:
 e.install_table(five_mowers=not a.four_mowers);e.instrument_mowers();e.clock_audio()
 if a.normal:e.battle_steps=e.normal_frames
 else:e.discard_pixels()
 try:
  if a.four_mowers:
   prepare(e,c,a.seed)
   while e.memory.u32(0x7013a0) and e.memory.u32(e.ELAPSED)<c.data['max_frames']:
    e.battle_steps(1000)
   result={'seed':a.seed,'frames':e.memory.u32(e.ELAPSED),'mower_frames':e.mower_times(),
           'active':e.memory.u32(0x7013a0),'state':state_data(e)}
  else:result=trial(e,c)
  result['success']=True
 except Exception as exc:
  result={'success':False,'error':repr(exc),'seed':a.seed,'process_exit':owner.game.poll()}
  for name,read in [('frames',lambda:e.memory.u32(e.ELAPSED)),
                    ('mower_frames',e.mower_times),('active',lambda:e.memory.u32(0x7013a0)),
                    ('context',lambda:e.memory.command('C')),('state',lambda:state_data(e))]:
   try:result[name]=read()
   except Exception as read_error:result[name+'_error']=repr(read_error)
  context=result.get('context','')
  match=re.search(r'\besi=([a-fA-F0-9]+)',context)
  if match:
   address=int(match[1],16)
   try:
    raw=e.memory.read(address,0x80)
    result['esi_object']={'address':address,'bytes':raw.hex(),
                           'floats':list(struct.unpack('<32f',raw))}
   except Exception:pass
 result['driver']='original outer loop' if a.normal else 'fast original update and draw'
 result['five_mower_rule']=not a.four_mowers
 a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print({k:v for k,v in result.items() if k not in ('state','checkpoints','esi_object')},flush=True)
