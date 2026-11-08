from pathlib import Path
import json,sys,time,os,subprocess
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare,state_data
out=Path('artifacts/normal-stall');out.mkdir(exist_ok=True)
c=Config.parse(json.loads(Path('examples/basic.json').read_text()))
g=GameProcess(log_dir=out/'logs')
with g as e:
 e.install_table();e.instrument_mowers();e.clock_audio();prepare(e,c,c.data['seed'])
 m=e.memory;m.put32(e.SHARED+0x14,5000);start=time.monotonic();last=-1;changed=start
 while True:
  frame=m.u32(e.ELAPSED);now=time.monotonic()
  if frame!=last:changed=now;last=frame
  if now-changed>5:
   print('STALLED',frame,now-start,m.command('C'),flush=True)
   print('app clocks',[m.u32(e.lawn+x) for x in (0x484,0x838)],'scene',m.u32(e.lawn+0x7fc),flush=True)
   (out/'state.json').write_text(json.dumps(state_data(e)))
   subprocess.run(['xwininfo','-root','-tree'],env={**os.environ,'DISPLAY':g.display})
   subprocess.run(['import','-window','root',str(out/'screen.png')],env={**os.environ,'DISPLAY':g.display})
   print('stack',m.read(int(m.command('C').split('esp=')[1].split()[0],16),0x100).hex(),flush=True)
   break
  if frame>=5000:print('completed',frame,now-start,flush=True);break
  time.sleep(.2)
