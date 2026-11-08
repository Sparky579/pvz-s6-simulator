"""Export per-lane mower times and descriptive statistics from a complete batch."""
from pathlib import Path
import argparse,csv,json,statistics


def percentile(values,quantile):
    ordered=sorted(values)
    position=(len(ordered)-1)*quantile
    left=int(position);right=min(left+1,len(ordered)-1)
    return ordered[left]+(ordered[right]-ordered[left])*(position-left)


def describe(frames):
    if not frames:
        return {k:(0 if k in ('count','sum_frames') else None) for k in
                ('count','sum_frames','mean_seconds','median_seconds','sample_sd_seconds',
                 'min_seconds','p05_seconds','p25_seconds','p75_seconds','p95_seconds','max_seconds')}
    seconds=[f/100 for f in frames]
    return {'count':len(seconds),'sum_frames':sum(frames),
            'mean_seconds':sum(frames)/(100*len(frames)),
            'median_seconds':statistics.median(seconds),
            'sample_sd_seconds':statistics.stdev(seconds) if len(seconds)>1 else None,
            'min_seconds':min(seconds),'p05_seconds':percentile(seconds,.05),
            'p25_seconds':percentile(seconds,.25),'p75_seconds':percentile(seconds,.75),
            'p95_seconds':percentile(seconds,.95),'max_seconds':max(seconds)}


def minutes_seconds(seconds):
    ticks=round(seconds*100)
    minutes,remainder=divmod(ticks,6000)
    return f'{minutes}:{remainder/100:05.2f}'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    parser.add_argument('--lanes',type=int,nargs='+',default=[1,3,5])
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--label',default='阵容时长统计',help='Human-readable experiment name')
    parser.add_argument('--allow-censored',action='store_true',help='Export incomplete lanes explicitly; means apply only to observed events')
    args=parser.parse_args()
    lanes=args.lanes
    if len(set(lanes))!=len(lanes) or any(l not in range(1,6) for l in lanes):
        raise ValueError('Lanes must be unique values in 1..5')
    data=json.loads(args.results.read_text());config=data['config'];trials=data['trials']
    expected=config['repetitions'];base_seed=config['seed']
    if len(trials)!=expected:raise ValueError(f'Incomplete batch: {len(trials)}/{expected} matches')
    expected_seeds={(base_seed+i)&0xffffffff for i in range(expected)}
    if len({t['seed'] for t in trials})!=expected or {t['seed'] for t in trials}!=expected_seeds:
        raise ValueError('Duplicate, missing or unexpected trial seeds')
    rows=[];all_frames=[];by_lane={l:[] for l in lanes};match_means=[];missing=[]
    for trial in sorted(trials,key=lambda t:(t['seed']-base_seed)&0xffffffff):
        match_index=((trial['seed']-base_seed)&0xffffffff)+1
        times=trial['mower_frames']
        if len(times)!=5:raise ValueError('Missing original mower event slots')
        selected=[]
        for lane in lanes:
            frame=times[lane-1] if trial.get('valid_for_statistics',True) else None
            if frame is None and args.allow_censored:
                cutoff=trial.get('frames')
                missing.append({'seed':trial['seed'],'lane':lane,'observed_through_frame':cutoff,
                                'status':trial['status'],'error':trial.get('error')})
                rows.append([match_index,trial['seed'],lane,'','','',cutoff,
                             '整局无效' if not trial.get('valid_for_statistics',True) else '未完成',trial['status']])
                continue
            if type(frame) is not int or not 0<=frame<=trial['frames']:
                raise ValueError(f'Incomplete lane: seed={trial["seed"]}, lane={lane}, frame={frame}')
            seconds=frame/100;all_frames.append(frame);by_lane[lane].append(frame);selected.append(frame)
            rows.append([match_index,trial['seed'],lane,frame,f'{seconds:.2f}',minutes_seconds(seconds),trial['frames'],'已触发',trial['status']])
        if len(selected)==len(lanes):match_means.append(statistics.fmean(selected)/100)
    overall=describe(all_frames)
    per_lane={str(l):{**describe(f),'unobserved_count':expected-len(f)} for l,f in by_lane.items()}
    # All matches contribute the same number of lanes. These independent
    # aggregations must therefore agree, including integer-frame totals.
    assert sum(v['sum_frames'] for v in per_lane.values())==overall['sum_frames']
    if not missing:assert abs(statistics.fmean(match_means)-overall['mean_seconds'])<1e-8
    summary={'matches':expected,'lanes_per_match':lanes,'lane_samples':expected*len(lanes),
             'requested_lane_samples':expected*len(lanes),'observed_lane_samples':len(all_frames),
             'unobserved_lane_samples':len(missing),'unobserved_lanes':missing,
             'complete':not missing,'overall_mean_is_observed_only':bool(missing),
             'invalid_matches':sum(not t.get('valid_for_statistics',True) for t in trials),
             'time_origin':'battle start','time_event':'first original mower trigger in the selected lane',
             'frames_per_second':100,'overall':overall,'by_lane':per_lane,
             'per_complete_match_selected_lane_mean':{'matches':len(match_means),
                 'mean_seconds':statistics.fmean(match_means) if match_means else None,
                 'sample_sd_seconds':statistics.stdev(match_means) if len(match_means)>1 else None},
             'config':config,'manifest':data['manifest'],'execution':data.get('execution'),
             'source':str(args.results.resolve()),
             'sampling_note':'Each match contributes paired lane results; selected lanes from one match are not independently run games.'}
    output=args.output_dir or args.results.parent;output.mkdir(parents=True,exist_ok=True)
    with (output/'lane_times.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['局编号','随机种子','路数','时长帧','时长秒','分:秒','最后观测帧','路线状态','对局状态']);writer.writerows(rows)
    (output/'statistics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    lines=[f'{args.label}：{expected} 局，计划 {expected*len(lanes)} 条路，有效已观测 {len(all_frames)} 条，未完成或整局无效 {len(missing)} 条',
           '', '时长：开战到本路推车首次触发，100 帧/秒。',
           '', '| 范围 | 已观测条数 | 平均秒数 | 平均分:秒 | 中位数（秒） | 标准差（秒） | 最短（秒） | 最长（秒） |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for label,item in [('合计',overall)]+[(f'第 {l} 路',per_lane[str(l)]) for l in lanes]:
        number=lambda v:f'{v:.2f}' if v is not None else '—'
        formatted_time=minutes_seconds(item['mean_seconds']) if item['mean_seconds'] is not None else '—'
        lines.append(f'| {label} | {item["count"]} | {number(item["mean_seconds"])} | '
                     f'{formatted_time} | {number(item["median_seconds"])} | '
                     f'{number(item["sample_sd_seconds"])} | {number(item["min_seconds"])} | {number(item["max_seconds"])} |')
    if missing:lines+=['','存在未完成路线：上表均值只针对已观测路线，不能作为全部计划路线的完整均值；未完成时刻不作推车触发时刻。']
    lines+=['',f'统计第 {"、".join(map(str,lanes))} 路；阵容、经验、模式和其他初始条件以 statistics.json 的 config 为准。',
            '同局各路来自同一原游戏进程，统计保留原 CT 的全部跨路机制。',
            '完整条件与执行指纹见 statistics.json，逐路原始时长见 lane_times.csv。']
    (output/'statistics.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':main()
