from pathlib import Path
import json,sys,struct,pefile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.parallel import Host
from s6.config import Config
from s6.runner import prepare,state_data
from s6.table import ROOT
from foley_calls import trace_foley_calls
c=Config.parse(json.loads(Path('artifacts/hard-day-upgrades.json').read_text()))
out=ROOT/'artifacts/foley-callers';out.mkdir(exist_ok=True)
pe=pefile.PE(str(ROOT/'build/audio_clock.dll'));buffers_rva=pe.sections[4].VirtualAddress+0x80
runs=[]
with Host(ROOT/'.wine-s6',out/'logs') as host:
 for normal in [False,True]:
  with GameProcess(prefix=host.prefix,display=host.display,keep_server=True,log_dir=out/'logs'/str(normal)) as e:
   e.install_table();e.instrument_mowers();e.clock_audio();e.trace_rng();prepare(e,c,c.data['seed']);foley_calls=trace_foley_calls(e)
   m=e.memory;foley=m.u32(e.lawn+0x784);types=m.u32(0x6a9f04);snapshots=[];trace=[]
   def snapshot():
    table=m.u32(e.SHARED+0x28)+buffers_rva;shadows={}
    for ptr in struct.unpack('<1024I',m.read(table,4096)):
     while ptr:
      value=struct.unpack('<I4xQQ6I',m.read(ptr,48));shadows[value[0]]=list(value[1:-1]);ptr=value[-1]
    data=m.read(foley,types*0xa4);active={}
    for kind in range(types):
     slots=[]
     for slot in range(8):
      words=list(struct.unpack_from('<5I',data,kind*0xa4+slot*20))
      if words[0]:
       instance=m.read(words[0],0x38);buffer=struct.unpack_from('<I',instance,0xc)[0]
       words[0]={'instance':words[0],'flags':instance[0x10:0x14].hex(),'buffer':buffer,'shadow':shadows.get(buffer)}
      slots.append(words)
     if any(s[1] or s[0] for s in slots):active[kind]={'slots':slots,'last_sample':struct.unpack_from('<I',data,kind*0xa4+0xa0)[0]}
    return {'frame':m.u32(e.ELAPSED),'foley':active,'state':state_data(e),'plants_raw':m.read(m.u32(e.board+0xac),m.u32(e.board+0xb0)*0x14c).hex()}
   advance=e.normal_frames if normal else e.battle_steps
   advance(940);snapshots.append(snapshot())
   for i in range(6):
    m.put32(e.RNG_COUNT,0);advance(1);trace.extend([list(r[:7])+[(r[7]-foley)//0xa4 if foley<=r[7]<foley+types*0xa4 else None] for r in e.rng_trace()]);snapshots.append(snapshot())
   runs.append({'normal':normal,'snapshots':snapshots,'rng':trace,'calls':foley_calls()});(out/'data.json').write_text(json.dumps(runs,indent=2));print('normal',normal,'frames',len(snapshots),'calls',[(v['frame'],v['kind'],hex(v['foley_caller'])) for v in foley_calls()],flush=True)
for a,b in zip(runs[0]['rng'],runs[1]['rng']):
 if a[:2]!=b[:2] or [x for x in a[2:7] if 0x400000<=x<0x652000]!=[x for x in b[2:7] if 0x400000<=x<0x652000]:
  print('first difference',a,b,flush=True);break
for a,b in zip(runs[0]['snapshots'],runs[1]['snapshots']):
 print('frame',a['frame'],'different foley kinds',flush=True)
 for kind in sorted(set(a['foley'])|set(b['foley'])):
  def clean(v):
   if not v:return v
   v=json.loads(json.dumps(v))
   for slot in v['slots']:
    if slot[0]:slot[0].pop('instance');slot[0].pop('buffer')
   return v
  left=clean(a['foley'].get(kind));right=clean(b['foley'].get(kind))
  if left!=right:print(kind,left,right,flush=True)
