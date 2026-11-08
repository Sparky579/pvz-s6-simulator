from pathlib import Path
import json,sys,struct
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.table import ROOT
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
out=ROOT/'artifacts/display';out.mkdir(exist_ok=True)
with GameProcess(prefix=ROOT/'.workers-s6/worker-07',log_dir=out/'logs') as e:
 m=e.memory;manager=m.u32(e.lawn+0x320);image=m.u32(manager+0x60);v=m.u32(image)
 print('image',hex(image),'vtable',hex(v),'size',m.u32(image+0x24),m.u32(image+0x28),flush=True)
 methods=struct.unpack('<64I',m.read(v,64*4));md=Cs(CS_ARCH_X86,CS_MODE_32);result=[]
 for index,address in enumerate(methods):
  if not 0x400000<=address<0x652000:break
  instructions=list(md.disasm(m.read(address,0x1800),address))
  returns=[(i.address,i.op_str) for i in instructions if i.mnemonic=='ret'][:2]
  result.append({'index':index,'address':address,'returns':returns})
  print(index,hex(address),returns,flush=True)
 (out/'methods.json').write_text(json.dumps(result,indent=2))
