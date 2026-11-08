"""Observe extreme native zombie animation-rate writes without changing values."""
from pathlib import Path
import argparse,json,struct,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare
from s6.table import ROOT
from native_observer import NativeObserver

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--seed',type=int,default=20261034)
p.add_argument('--prefix',type=Path,default=ROOT/'.workers-s6/worker-14')
p.add_argument('--observe',action='store_true')
a=p.parse_args()
out=ROOT/f'artifacts/ji-huo-lie-huo-xian-200-20261027/rate-trace-{a.seed}'
out.mkdir(parents=True,exist_ok=True)
d=json.loads((ROOT/'examples/ji_huo_lie_huo_xian_135.json').read_text())
d.update(seed=a.seed,repetitions=1,max_frames=170000);config=Config.parse(d)
with GameProcess(prefix=a.prefix,log_dir=out/'logs') as e:
 e.install_table();e.instrument_mowers();e.clock_audio();e.discard_pixels()
 prepare(e,config,config.data['seed'])
 observer=NativeObserver(e) if a.observe else None
 if observer:
  original_wait=e.wait
  def checked_wait(predicate,timeout,what):
   def check():
    records=observer.records()
    if records:raise RuntimeError(f'Original first-chance exception: {hex(records[-1]["eip"])}')
    return predicate()
   return original_wait(check,timeout,what)
  e.wait=checked_wait
 log=e.memory.alloc(4096*128);counter=e.SHARED+0x100
 e.memory.put32(counter,0)
 def record(zombie,rate,source,return_address):
  fields=[f'mov eax,dword ptr [0x{e.ELAPSED:x}]',f'mov eax,{source}',
          f'mov eax,{return_address}','mov eax,ebp','mov eax,edx']
  fields += [f'mov eax,dword ptr [ebp+0x{o:x}]' for o in
             (0x24,0x1c,0x28,0x2c,0x34,0x11c,0x118,0x124,0xc8,0x130)]
  writes=';'.join(f'{line};mov dword ptr [edi+{i*4}],eax' for i,line in enumerate(fields))
  return f'''
   pushfd;pushad;mov edx,{rate};cmp edx,0x447a0000;jbe done;
   mov ebp,{zombie};mov ecx,dword ptr [0x{counter:x}];mov edi,ecx;
   and edi,4095;shl edi,7;add edi,0x{log:x};
   {writes};mov dword ptr [edi+60],ecx;
   lea esi,[esp+36];add edi,64;mov ecx,16;
   rep movsd dword ptr es:[edi],dword ptr [esi];
   inc dword ptr [0x{counter:x}];
  done:popad;popfd;
  '''
 hooks=[(0x52eff0,bytes.fromhex('8b 08 8b 90 18 01 00 00'),
         record('eax','dword ptr [esp+40]',0x52eff0,'dword ptr [esp+36]')+
         'mov ecx,dword ptr [eax];mov edx,dword ptr [eax+0x118]'),
        (0x532e25,bytes.fromhex('d9 5f 08 83 7e 28 26'),
         'fstp dword ptr [edi+8];'+record('esi','dword ptr [edi+8]',0x532e25,'0')+
         'cmp dword ptr [esi+0x28],0x26')]
 for i,(site,expected,code) in enumerate(hooks):
  if e.memory.read(site,len(expected))!=expected:raise RuntimeError(f'Native hook mismatch: {site:x}')
  target=e.BASE+0xc000+i*0x1000
  e.memory.write(target,e.asm(code+f';jmp 0x{site+len(expected):x}',target))
  e.memory.write(site,e.asm(f'jmp 0x{target:x}',site)+b'\x90'*(len(expected)-5))
 error=None
 attachment_history=[]
 try:
  while e.memory.u32(e.ELAPSED)<170000 and e.memory.u32(0x7013a0):
   holder=e.memory.u32(e.memory.u32(0x6a9eb8)+0xc)
   attachment_history.append({'frame':e.memory.u32(e.ELAPSED),
                              'header':list(struct.unpack('<7I',e.memory.read(holder,28)))})
   e.battle_steps(1000)
 except Exception as exc:error=repr(exc)
 count=e.memory.u32(counter)
 raw=e.memory.read(log,4096*128);events=[]
 for i in range(4096):
  values=struct.unpack_from('<32I',raw,i*128)
  if values[0]==0 or not max(0,count-4096)<=values[15]<count:continue
  names='frame source caller zombie rate_bits zombie_type row phase x_bits speed_bits scale_bits body_id default_rate_bits hp chill sequence'.split()
  event=dict(zip(names,values[:16]));event['stack']=list(values[16:])
  for name in ('rate','x','speed','scale','default_rate'):
   value=struct.unpack('<f',struct.pack('<I',event[name+'_bits']))[0]
   event[name]=value
  events.append(event)
 events.sort(key=lambda x:x['sequence'])
 result={'seed':config.data['seed'],'error':error,'frames':e.memory.u32(e.ELAPSED),
         'mower_frames':e.mower_times(),'events_written':count,'events':events,
         'instrumentation':'preserves original integer flags/registers, x87 instructions and rate values'}
 if observer:result['exceptions']=observer.records()
 result['attachment_history']=attachment_history
 try:
  holder=e.memory.u32(e.memory.u32(0x6a9eb8)+0xc)
  result['attachment_header_at_end']=list(struct.unpack('<7I',e.memory.read(holder,28)))
 except RuntimeError:pass
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print({k:v for k,v in result.items() if k!='events'},flush=True)
 for event in events[-8:]:print(event,flush=True)
