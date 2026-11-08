from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.process import GameProcess
from s6.config import Config
from s6.runner import prepare

config=Config.parse({'formation':[[3,None,None,None,None] for _ in range(5)],'seed':42})
with GameProcess(log_dir=Path('artifacts/mower-boundary/logs')) as engine:
    engine.install_table();engine.instrument_mowers();engine.clock_audio()
    prepare(engine,config,42)
    m=engine.memory;board=engine.board
    engine.execute(f'push 0;push 0;mov eax,0x{board:x};call 0x40ddc0')
    base=m.u32(board+0x100);used=m.u32(board+0x104)
    by_row={}
    for i in range(used):
        p=base+i*0x48
        if not m.read(p+0x30,1)[0]:by_row[m.u32(p+0x14)]=p
    if set(by_row)!=set(range(5)):raise AssertionError(by_row)
    for row in range(4):engine.execute(f'mov esi,0x{by_row[row]:x};call 0x458da0')
    engine.battle_steps(1)
    after_four={'active':m.u32(0x7013a0),'mower_frames':engine.mower_times()}
    if after_four['active']!=1:raise AssertionError(after_four)
    engine.execute(f'mov esi,0x{by_row[4]:x};call 0x458da0')
    engine.battle_steps(1)
    after_five={'active':m.u32(0x7013a0),'mower_frames':engine.mower_times()}
    if after_five['active']!=0 or any(t<0 for t in after_five['mower_frames']):raise AssertionError(after_five)
    result={'after_four':after_four,'after_five':after_five}
    Path('artifacts/mower-boundary/result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
