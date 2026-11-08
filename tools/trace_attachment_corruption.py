"""Record native attachment appends near their 16-item storage boundary."""
from pathlib import Path
import json,struct,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare
from s6.table import ROOT
from native_observer import NativeObserver

out=ROOT/'artifacts/ji-huo-lie-huo-xian-200-20261027/attachment-trace-20261050'
out.mkdir(parents=True,exist_ok=True)
d=json.loads((ROOT/'examples/ji_huo_lie_huo_xian_135.json').read_text())
d.update(seed=20261050,repetitions=1);config=Config.parse(d)
with GameProcess(prefix=ROOT/'.workers-s6/worker-14',log_dir=out/'logs') as e:
 e.install_table();e.instrument_mowers();e.clock_audio();e.discard_pixels()
 prepare(e,config,config.data['seed']);observer=NativeObserver(e)
 original_wait=e.wait
 def checked_wait(predicate,timeout,what):
  def check():
   records=observer.records()
   if records:raise RuntimeError(f'Original first-chance exception: {hex(records[-1]["eip"])}')
   return predicate()
  return original_wait(check,timeout,what)
 e.wait=checked_wait
 site=0x405581;original=bytes.fromhex('8b 82 00 03 00 00 8d 0c 40')
 if e.memory.read(site,9)!=original:raise RuntimeError('Attachment append entry changed')
 log=e.memory.alloc(4096*128);counter=e.SHARED+0x100;e.memory.put32(counter,0)
 thunk=e.BASE+0xc000
 source=f'''
  pushfd;pushad;
  cmp dword ptr [edx+0x300],14;jb done;
  mov ebp,edx;mov ebx,edi;mov ecx,dword ptr [0x{counter:x}];
  mov edi,ecx;and edi,4095;shl edi,7;add edi,0x{log:x};
  mov dword ptr [edi],ecx;
  mov eax,dword ptr [0x{e.ELAPSED:x}];mov dword ptr [edi+4],eax;
  mov dword ptr [edi+8],ebp;mov dword ptr [edi+12],ebx;
  mov eax,dword ptr [ebp+0x300];mov dword ptr [edi+16],eax;
  mov eax,dword ptr [ebp+0x308];mov dword ptr [edi+20],eax;
  movzx eax,byte ptr [ebp+0x304];mov dword ptr [edi+24],eax;
  mov eax,dword ptr [ebx];mov dword ptr [edi+28],eax;
  lea esi,[esp+36];add edi,32;mov ecx,24;
  rep movsd dword ptr es:[edi],dword ptr [esi];
  inc dword ptr [0x{counter:x}];
 done:popad;popfd;
  mov eax,dword ptr [edx+0x300];lea ecx,[eax+eax*2];jmp 0x{site+9:x};
 '''
 e.memory.write(thunk,e.asm(source,thunk));e.memory.write(site,e.asm(f'jmp 0x{thunk:x}',site)+b'\x90'*4)
 error=None
 try:
  while e.memory.u32(e.ELAPSED)<155000 and e.memory.u32(0x7013a0):e.battle_steps(1000)
 except Exception as exc:error=repr(exc)
 count=e.memory.u32(counter);raw=e.memory.read(log,4096*128);events=[]
 for i in range(4096):
  values=struct.unpack_from('<32I',raw,i*128)
  if not values[1] or not max(0,count-4096)<=values[0]<count:continue
  names='sequence frame attachment owner count id dead owner_id'.split()
  event=dict(zip(names,values[:8]));event['stack']=list(values[8:])
  event['locations']={hex(v):observer.describe_address(v) for v in values[8:] if observer.describe_address(v)}
  events.append(event)
 events.sort(key=lambda x:x['sequence'])
 holder=e.memory.u32(e.memory.u32(0x6a9eb8)+0xc)
 result={'seed':config.data['seed'],'frame':e.memory.u32(e.ELAPSED),'error':error,
         'mower_frames':e.mower_times(),'events_written':count,'events':events,
         'attachment_header':list(struct.unpack('<7I',e.memory.read(holder,28))),
         'exceptions':observer.records()}
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print({k:v for k,v in result.items() if k not in ('events','exceptions')},flush=True)
 for event in events[-6:]:print(event,flush=True)
