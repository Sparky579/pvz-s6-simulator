"""Observe a prepared original game without advancing the battle."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config
from s6.process import GameProcess
from s6.runner import prepare,state_data
from s6.table import ROOT

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();data=json.loads(a.input.read_text());config=Config.parse(data.get('config',data))
a.output.parent.mkdir(parents=True,exist_ok=True)
with GameProcess(prefix=ROOT/'.workers-s6/worker-00',log_dir=a.output.parent/'logs') as e:
    e.install_table();e.instrument_mowers();e.clock_audio();e.discard_pixels()
    prepare(e,config,config.data['seed'])
    address=e.BASE+0x11000;e.memory.write(address,b'S6AudioBuffers\0')
    e.execute(f'push 0x{address:x};push dword ptr [0x{e.SHARED+0x28:x}];'
              f'call dword ptr [0x{e.api["GetProcAddress"]:x}];mov eax,[eax];'
              f'mov dword ptr [0x{e.SHARED+0xa0:x}],eax')
    result={'state':state_data(e),'audio_buffers_registered':e.memory.u32(e.SHARED+0xa0),
            'clocks':{'app838':e.memory.u32(e.lawn+0x838),'app484':e.memory.u32(e.lawn+0x484)}}
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Saved initial state; audio buffers:',result['audio_buffers_registered'],flush=True)
