import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import trial
from capstone import Cs,CS_ARCH_X86,CS_MODE_32

with GameProcess(log_dir=Path('artifacts/diagnose')) as x:
 p=x.install_table();x.instrument_mowers()
 Path('artifacts/diagnose/programs.json').write_text(json.dumps([{ 'id':i,'writes':[(hex(a),len(b)) for a,b in p.writes]} for i,p in p],indent=2))
 for type_id in [25,23,3,7]:
  f=[[7]*5 for _ in range(5)]
  f[0][2]=type_id
  c=Config.parse({'formation':f,'max_frames':20,'seed':20261026})
  print('TYPE',type_id,flush=True)
  try:r=trial(x,c);print(r['status'],r['frames'],flush=True)
  except Exception:
   text=Path('artifacts/diagnose/game.log').read_text(errors='replace')
   es=re.findall(r'dispatch_exception code=c000\w+ flags=\w+ addr=([0-9a-f]+)',text,re.I)
   if es:
    a=int(es[-1],16);print('fault',hex(a))
    for i,p in p:
     for addr,data in p.writes:
      if addr<=a<addr+len(data):print('fault CT',i,'offset',hex(a-addr))
    try:
     data=x.memory.read(a-32,128);print('raw',data.hex())
     for ins in Cs(CS_ARCH_X86,CS_MODE_32).disasm(data,a-32):print(hex(ins.address),ins.mnemonic,ins.op_str)
    except Exception as e:print('readerror',e)
   raise
