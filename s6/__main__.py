from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import sys
from .config import Config
from .parallel import run_batch
from .runner import manifest


def main():
    parser=argparse.ArgumentParser(description='S6 原引擎无前端测阵器（原 CT bug 保留，五路推车触发结束）')
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('config',type=Path)
    run.add_argument('-o','--output',type=Path,required=True)
    run.add_argument('--repetitions',type=int);run.add_argument('--seed',type=int)
    run.add_argument('--workers',type=int,default=0,help='并行工作线程数量；0 按 CPU 和可用内存自动选择')
    run.add_argument('--reuse-game',action='store_true',help='同一线程复用原游戏进程和资源缓存，减少每局加载耗时')
    run.add_argument('--speed-mode',choices=('exact','fast'),help='exact 保留完整原绘制；fast 每帧保留 CT 回调并省略原场景绘制')
    replay=sub.add_parser('replay');replay.add_argument('result',type=Path);replay.add_argument('--index',type=int,default=0)
    replay.add_argument('-o','--output',type=Path,required=True)
    inspect=sub.add_parser('inspect');inspect.add_argument('--speed-mode',choices=('exact','fast'),default='exact')
    args=parser.parse_args()
    if args.command=='inspect':print(json.dumps(manifest(args.speed_mode),ensure_ascii=False,indent=2));return
    reference=None
    if args.command=='run':
        data=json.loads(args.config.read_text())
        if args.repetitions is not None:data['repetitions']=args.repetitions
        if args.seed is not None:data['seed']=args.seed
        if args.speed_mode is not None:data['speed_mode']=args.speed_mode
    else:
        prior=json.loads(args.result.read_text());data=prior['config']
        reference=prior['trials'][args.index]
        if prior['manifest']!=manifest(data.get('speed_mode','exact')):raise ValueError('Original package/rule manifest differs from replay input')
        data={**data,'seed':reference['seed'],'repetitions':1}
    config=Config.parse(data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result={'manifest':manifest(config.data['speed_mode']),'config':config.data,'config_sha256':config.digest,'trials':[]}
    completed={}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def on_result(index,item):
        completed[index]=item;result['trials']=[completed[i] for i in sorted(completed)]
        print(f'{len(completed)}/{config.data["repetitions"]}: seed={item["seed"]}, {item["status"]}, {item["game_seconds"]:.2f}s, {item["speedup"]:.1f}x',file=sys.stderr,flush=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    trials,execution=run_batch(config,workers=args.workers if args.command=='run' else 1,
                               log_dir=args.output.parent/'logs',on_result=on_result,
                               reuse_game=args.command=='run' and args.reuse_game)
    result['trials']=trials;result['execution']=execution
    result['execution']['aggregate_speedup']=sum(t['game_seconds'] for t in trials)/execution['wall_seconds']
    result['summary']={'trials':len(result['trials']),
                       'mean_game_seconds':statistics.mean(t['game_seconds'] for t in result['trials']),
                       'completed':sum(t['status']=='all_mowers_triggered' for t in result['trials'])}
    if reference:
        actual=result['trials'][0]
        result['replay_matches']=all(actual[k]==reference[k] for k in ('seed','status','frames','mower_frames','checkpoints'))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if reference and not result['replay_matches']:raise SystemExit('Replay diverged; inspect checkpoint hashes')


if __name__=='__main__':main()
