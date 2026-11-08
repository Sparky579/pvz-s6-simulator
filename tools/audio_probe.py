from pathlib import Path
import json,sys,struct
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
c=Config.parse(json.loads(Path('examples/basic.json').read_text()))
with GameProcess(log_dir=Path('artifacts/audio-probe/logs')) as x:
 x.install_table();x.instrument_mowers()
 prepare(x,c,c.data['seed']);x.battle_steps(350)
 m=x.memory;foley=m.u32(x.lawn+0x784);types=m.u32(0x6a9f04)
 print('foley',hex(foley),'types',types,'soundmanager',hex(m.u32(x.lawn+0x4b4)),flush=True)
 seen=set()
 for i in range(types):
  for j in range(8):
   p=m.u32(foley+i*0xa4+j*0x14)
   if not p:continue
   v=m.u32(p)
   print('slot',i,j,hex(p),'vtable',hex(v),'data',m.read(p,0x80).hex(),flush=True)
   if v in seen:continue
   seen.add(v)
   methods=struct.unpack('<12I',m.read(v,48));print('methods',[hex(a) for a in methods],flush=True)
   for index in [4,7,8,9]:
    a=methods[index];print('METHOD',index,hex(a),flush=True)
    for ins in Cs(CS_ARCH_X86,CS_MODE_32).disasm(m.read(a,120),a):
     print(hex(ins.address),ins.mnemonic,ins.op_str,flush=True)
     if ins.mnemonic.startswith('ret'):break
