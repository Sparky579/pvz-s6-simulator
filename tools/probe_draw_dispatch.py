from pathlib import Path
import json,sys,struct,pefile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare
from s6.table import ROOT,GAME
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
out=ROOT/'artifacts/draw-dispatch';out.mkdir(exist_ok=True)
c=Config.parse(json.loads((ROOT/'artifacts/hard-day-upgrades.json').read_text()))
with GameProcess(prefix=ROOT/'.workers-s6/worker-07',log_dir=out/'logs') as e:
 e.install_table();e.instrument_mowers();e.clock_audio();prepare(e,c,c.data['seed']);m=e.memory
 manager=m.u32(e.lawn+0x320);count=e.SHARED+0x68;callback=e.BASE+0xe00
 old=m.read(0x41a2c2,5);target=0x41a2c2+5+struct.unpack('<i',old[1:])[0]
 code=f'''pushfd;pushad;inc dword ptr [0x{count:x}];mov dword ptr [0x{count+4:x}],edx;mov dword ptr [0x{count+8:x}],edi;mov esi,edi;mov edi,0x{e.BASE+0x9000:x};mov ecx,26;rep movsd dword ptr es:[edi],dword ptr [esi];popad;popfd;jmp 0x{target:x}'''
 m.write(callback,e.asm(code,callback));m.write(0x41a2c2,e.asm(f'jmp 0x{callback:x}',0x41a2c2))
 result={};methods={}
 for name,obj in [('app',e.lawn),('manager',manager),('board',e.board)]:
  table=m.u32(obj);values=struct.unpack('<72I',m.read(table,72*4));result[name]={'object':obj,'vtable':table,'methods':list(values)}
  print(name,hex(obj),hex(table),[(hex(i*4),hex(v)) for i,v in enumerate(values) if name!='board' and i in (8,10,13)],flush=True)
  if name=='app':methods['app34']=values[13]
  if name=='manager':methods['manager28']=values[10]
 result['counts']=[]
 for mode in ['rendered','normal','rendered']:
  (lambda:e.battle_steps(1,render=True))() if mode=='rendered' else e.normal_frames(1)
  record={'mode':mode,'count':m.u32(count),'manager':m.read(manager,0x150).hex(),'graphics_ptr':m.u32(count+8),'graphics':m.read(e.BASE+0x9000,104).hex()}
  result['counts'].append(record);print(mode,'count',record['count'],'graphics',hex(record['graphics_ptr']),flush=True)
 md=Cs(CS_ARCH_X86,CS_MODE_32)
 for name,address in methods.items():
  print(name,hex(address),flush=True)
  for i in md.disasm(m.read(address,180),address):print(hex(i.address),i.mnemonic,i.op_str,flush=True)
 (out/'data.json').write_text(json.dumps(result,indent=2))
