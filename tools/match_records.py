"""Durable per-match replay inputs and a document updated after every result."""
from pathlib import Path
from datetime import datetime,timezone
import csv,hashlib,io,json,os,platform,subprocess


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    os.replace(temporary,path)


def clock_time(frame):
    if frame is None:return '未完成'
    minute,rest=divmod(frame,6000)
    return f'{minute}:{rest/100:05.2f}'


def winner(trial):
    if not trial.get('valid_for_statistics',True):return []
    times=trial['mower_frames']
    if any(t is None for t in times):return []
    longest=max(times)
    return [i+1 for i,t in enumerate(times) if t==longest]


class MatchRecorder:
    def __init__(self,directory,config,manifest):
        self.directory=Path(directory);self.config=config;self.manifest=manifest
        self.environment={'hostname':platform.node(),'platform':platform.platform(),
                          'python':platform.python_version(),
                          'wine':subprocess.check_output(['wine','--version'],text=True).strip()}
        self.manifest_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def location(self,seed):
        index=((seed-self.config.data['seed'])&0xffffffff)+1
        return Path('matches')/f'{index:04d}-seed-{seed}'

    def begin(self,seed):
        from s6.config import Config
        config=Config.parse({**self.config.data,'seed':seed,'repetitions':1})
        initial={'manifest':self.manifest,'manifest_sha256':self.manifest_sha256,
                 'config':config.data,'config_sha256':config.digest,
                 'match_index':((seed-self.config.data['seed'])&0xffffffff)+1,
                 'runtime_environment':self.environment,'setup_complete':False,
                 'created_utc':datetime.now(timezone.utc).isoformat(),
                 'note':'Replay recipe and selected initial gameplay state; not a full process checkpoint or a recorded video.'}
        atomic_json(self.directory/self.location(seed)/'initial_conditions.json',initial)
        return initial

    def prepared(self,engine,seed,initial):
        from s6.runner import state_data
        snapshot=state_data(engine)
        initial.update(setup_complete=True,initial_state=snapshot,
                       initial_state_sha256=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                       actual_initial_clocks={'LawnApp+0x838':engine.memory.u32(engine.lawn+0x838),
                                             'SexyAppBase+0x484':engine.memory.u32(engine.lawn+0x484)},
                       actual_battle_frame=engine.memory.u32(engine.ELAPSED))
        atomic_json(self.directory/self.location(seed)/'initial_conditions.json',initial)

    def finish(self,item):
        location=self.location(item['seed'])
        initial=json.loads((self.directory/location/'initial_conditions.json').read_text())
        valid=item['status']=='all_mowers_triggered' and all(t is not None for t in item['mower_frames'])
        item['valid_for_statistics']=valid
        item['invalid_reason']=None if valid else item['status']
        item.update(runtime_environment=self.environment,
                    initial_conditions_file=(location/'initial_conditions.json').as_posix(),
                    replay_file=(location/'replay.json').as_posix(),
                    lane_seconds=[t/100 for t in item['mower_frames']] if valid else [None]*5,
                    winner_lanes=winner(item),winner_confirmed=valid)
        bundle={'manifest':self.manifest,'config':initial['config'],
                'config_sha256':initial['config_sha256'],'trials':[dict(item)],
                'initial_conditions':initial,'source_match_index':initial['match_index']}
        atomic_json(self.directory/location/'replay.json',bundle)


def write_documents(directory,result):
    """Rewrite atomically from durable results, including during shard merging."""
    directory=Path(directory);base=result['config']['seed'];trials=result['trials']
    rows=sorted(trials,key=lambda t:(t['seed']-base)&0xffffffff)
    lines=['# 逐局五路时长记录','',
           f'计划 {result["config"]["repetitions"]} 局；已记录 {len(rows)} 局。每局完成后更新。',
           '','时长为开战至本路首次触发原小推车；坚持最久的路获胜，同帧并列。卡死或原生异常整局五路全部无效，不计时长及胜负，不补局；原始时刻只留在 JSON 诊断。达到帧数上限也单列为未完成，不计胜负。',
           '', '初始条件、机器及执行指纹保存在每局链接中。全局配置见 results.json；所有时长按 100 帧/秒换算。',
           '', '| 局号 | 种子 | 第1路 | 第2路 | 第3路 | 第4路 | 第5路 | 胜出路 | 状态 | 初始条件 / 重放 |',
           '| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |']
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['局号','种子','机器','第1路秒','第2路秒','第3路秒','第4路秒','第5路秒','胜出路','状态','初始条件','重放文件'])
    for t in rows:
        index=((t['seed']-base)&0xffffffff)+1
        valid=t.get('valid_for_statistics',True)
        winners=winner(t);label='、'.join(map(str,winners)) if winners else ('无效' if not valid else '未确定')
        initial=t.get('initial_conditions_file','');replay=t.get('replay_file','')
        links=f'[初始]({initial}) / [重放]({replay})' if initial and replay else '未保存独立记录'
        times=[clock_time(f) for f in t['mower_frames']] if valid else ['无效']*5
        lines.append(f'| {index} | {t["seed"]} | '+' | '.join(times)+
                     f' | {label} | {t["status"]} | {links} |')
        writer.writerow([index,t['seed'],t.get('runtime_environment',{}).get('hostname',''),
                         *[f'{f/100:.2f}' if valid and f is not None else '' for f in t['mower_frames']],
                         label,t['status'],initial,replay])
    directory.mkdir(parents=True,exist_ok=True)
    for name,content in [('matches.md','\n'.join(lines)+'\n'),('matches.csv','\ufeff'+stream.getvalue())]:
        target=directory/name;temporary=target.with_suffix(target.suffix+'.tmp')
        temporary.write_text(content);os.replace(temporary,target)
