from pathlib import Path
import argparse,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare,state_data
from native_observer import NativeObserver
from capstone import Cs,CS_ARCH_X86,CS_MODE_32

p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=Path('artifacts/night-ice-config.json'))
p.add_argument('--frames',type=int,default=5000);p.add_argument('--output',type=Path,default=Path('artifacts/draw-exception/data.json'))
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
c=Config.parse(json.loads(a.config.read_text()))
with GameProcess(log_dir=a.output.parent/'logs') as e:
 e.install_table();e.instrument_mowers();e.clock_audio();observer=NativeObserver(e)
 prepare(e,c,c.data['seed']);e.memory.put32(observer.count,0)
 e.memory.put32(e.SHARED+0x14,a.frames);deadline=time.monotonic()+a.frames/100+30
 while time.monotonic()<deadline:
  records=observer.records()
  if records:
   record=records[-1];code={};md=Cs(CS_ARCH_X86,CS_MODE_32)
   for address in [record['eip']]+record['stack']:
    where=observer.describe_address(address)
    if not where:continue
    start=address if address==record['eip'] else address-20
    try:instructions=list(md.disasm(e.memory.read(start,100),start))
    except RuntimeError:continue
    code[hex(address)]={'where':where,'assembly':[f'{i.address:08x}: {i.mnemonic} {i.op_str}' for i in instructions]}
   result={'config':c.data,'frame':e.memory.u32(e.ELAPSED),'records':records,'code':code,'state':state_data(e)}
   a.output.write_text(json.dumps(result,indent=2)+'\n')
   print('exception frame',result['frame'],'code',hex(record['code']),'at',hex(record['eip']),flush=True)
   for address,values in code.items():
    print(address,values['where'],flush=True)
    if values['where'].get('ct_entry'):print('\n'.join(values['assembly']),flush=True)
   break
  if e.memory.u32(e.SHARED+0x14)==0 and e.memory.u32(e.SHARED+4)==1:
   print('No exception in',a.frames,'frames',flush=True);break
  time.sleep(.05)
 else:raise TimeoutError('Neither frame completion nor observed exception')
