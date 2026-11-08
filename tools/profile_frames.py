"""Measure original update/draw CPU time without replacing either callback."""
from pathlib import Path
import argparse,json,struct,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare,state_data

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('config',type=Path)
p.add_argument('--frames',type=int,default=5000)
p.add_argument('--warmup',type=int,default=0)
p.add_argument('--prefix',type=Path)
p.add_argument('--fast-audio',action='store_true')
p.add_argument('--no-draw',action='store_true')
p.add_argument('--fast-drawing',action='store_true')
p.add_argument('--calls',action='store_true',help='Time original LawnApp::Update subcalls')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
c=Config.parse(json.loads(a.config.read_text()))
with GameProcess(prefix=a.prefix,log_dir=a.output.parent/'logs') as e:
 e.install_table();e.instrument_mowers()
 if a.fast_audio:
  from fast_audio_device import install
  install(e)
 else:e.clock_audio()
 e.discard_pixels()
 prepare(e,c,c.data['seed'])
 if a.fast_drawing:
  from fast_drawing import install
  install(e)
 for offset in range(0,a.warmup,1000):e.battle_steps(min(1000,a.warmup-offset))
 base=e.SHARED+0x100
 e.memory.write(base,bytes(48))
 call_slots={}
 if a.calls:
  for index,(site,target,op,stack_bytes) in enumerate(((0x4526f0,0x41bad0,'call',0),(0x4526f7,0x5d59a0,'call',0),
                                        (0x452702,0x45b670,'call',0),(0x452722,0x4524f0,'call',0),
                                        (0x5d59a3,0x54b980,'call',0),(0x5d59af,0x5ab200,'jmp',0),
                                        (0x54b99a,0x539140,'call',0),(0x54b9b8,0x555850,'call',4),
                                        (0x415d8d,0x43c200,'call',0),(0x415d94,0x40eab0,'call',0),
                                        (0x415e8c,0x445890,'call',0),(0x415e97,0x4594b0,'call',0),
                                        (0x415e9d,0x4144e0,'call',4),(0x415f66,0x416080,'call',4),
                                        (0x416010,0x41d730,'call',0),(0x416017,0x41d630,'call',0),
                                        (0x41601e,0x415920,'call',0),(0x416024,0x41a5d0,'call',4),
                                        (0x41602f,0x4246b0,'call',0),(0x416035,0x40bf60,'call',4))):
   if e.memory.read(site,5)!=e.asm(f'{op} 0x{target:x}',site):
    raise RuntimeError(f'Profile call site changed: {site:x}')
   slot=e.SHARED+0x400+index*32;thunk=e.BASE+0xc000+index*256
   e.memory.write(slot,bytes(32));call_slots[hex(target)]=slot
   args=f'push dword ptr [esp+{stack_bytes}];'*(stack_bytes//4)
   ret=f'ret {stack_bytes}' if stack_bytes else 'ret'
   e.memory.write(thunk,e.asm(f'''
    pushfd;pushad;rdtsc;mov dword ptr [0x{slot:x}],eax;mov dword ptr [0x{slot+4:x}],edx;popad;popfd;
    {args}call 0x{target:x};
    pushfd;pushad;rdtsc;sub eax,dword ptr [0x{slot:x}];sbb edx,dword ptr [0x{slot+4:x}];
    add dword ptr [0x{slot+8:x}],eax;adc dword ptr [0x{slot+12:x}],edx;
    inc dword ptr [0x{slot+16:x}];popad;popfd;{ret};''',thunk))
   e.memory.write(site,e.asm(f'{op} 0x{thunk:x}',site))
 def mark(offset):
  return f'pushad;rdtsc;mov dword ptr [0x{base+offset:x}],eax;mov dword ptr [0x{base+offset+4:x}],edx;popad;'
 def accumulate(left,right,total):
  return f'''pushad;mov eax,dword ptr [0x{base+right:x}];mov edx,dword ptr [0x{base+right+4:x}];
   sub eax,dword ptr [0x{base+left:x}];sbb edx,dword ptr [0x{base+left+4:x}];
   add dword ptr [0x{base+total:x}],eax;adc dword ptr [0x{base+total+4:x}],edx;popad;'''
 started=time.monotonic()
 e.execute(f'''mov dword ptr [0x{e.SHARED+8:x}],{a.frames};tick:
  inc dword ptr [0x{e.ELAPSED:x}];{mark(0)}
  mov ecx,dword ptr [0x6a9ec0];call 0x{e.TRAMP:x};{mark(8)}
  {e.draw_frame_source() if not a.no_draw else ''};{mark(16)}
  {accumulate(0,8,24)}{accumulate(8,16,32)}
  cmp dword ptr [0x7013a0],0;je done;
  dec dword ptr [0x{e.SHARED+8:x}];jnz tick;done:''')
 elapsed=time.monotonic()-started
 values=struct.unpack('<6Q',e.memory.read(base,48))
 result={'frames':e.memory.u32(e.ELAPSED),'warmup_frames':a.warmup,'wall_seconds':elapsed,
         'update_cycles':values[3],'draw_cycles':values[4],
         'draw_fraction':values[4]/(values[3]+values[4]),
         'screen_raster_calls':e.memory.u32(e.display_counter),'state':state_data(e)}
 if call_slots:
  result['calls']={name:{'cycles':struct.unpack('<Q',e.memory.read(slot+8,8))[0],
                         'count':e.memory.u32(slot+16)} for name,slot in call_slots.items()}
 a.output.write_text(json.dumps(result,indent=2)+'\n')
 print({k:v for k,v in result.items() if k!='state'})
