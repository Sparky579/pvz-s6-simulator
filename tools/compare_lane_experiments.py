"""Compare complete, paired seed plans without replacing failed native trials."""
from pathlib import Path
import argparse,json,statistics,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.config import Config


def read(path):
    data=json.loads(path.read_text())
    config=Config.parse(data['config']).data
    plan={(config['seed']+i)&0xffffffff for i in range(config['repetitions'])}
    trials={t['seed']:t for t in data['trials']}
    if len(trials)!=len(data['trials']) or set(trials)!=plan:
        raise ValueError(f'{path}: incomplete, duplicate or unexpected seeds')
    return data,config,trials


def describe(frames):
    return {'count':len(frames),
            'mean_seconds':sum(frames)/100/len(frames) if frames else None,
            'median_seconds':statistics.median(frames)/100 if frames else None}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    original,oc,old=read(a.baseline);candidate,nc,new=read(a.candidate)
    if {k:v for k,v in oc.items() if k!='speed_mode'}!={k:v for k,v in nc.items() if k!='speed_mode'}:
        raise ValueError('Game conditions or seed plans differ')
    for field in ('exe_sha256','ct_sha256','gdi42_sha256','dllmain_sha256'):
        if original['manifest'][field]!=candidate['manifest'][field]:
            raise ValueError(f'Original input differs: {field}')
    differences=[];common_old=[];common_new=[];endpoint_differences=[];unknown=[];completed_equal=0
    for seed,o in old.items():
        n=new[seed]
        if o.get('frames') is None:unknown.append(seed)
        for field in ('status','frames','mower_frames','checkpoints'):
            if o.get(field)!=n.get(field):differences.append({'seed':seed,'field':field})
        if o['status']==n['status']=='all_mowers_triggered' and all(o[k]==n[k] for k in ('frames','mower_frames','checkpoints')):
            completed_equal+=1
        for lane in (1,3,5):
            x=o['mower_frames'][lane-1];y=n['mower_frames'][lane-1]
            if x is not None and y is not None:
                common_old.append(x);common_new.append(y)
                if x!=y:endpoint_differences.append({'seed':seed,'lane':lane,'baseline_frames':x,'candidate_frames':y})
    report={'baseline':str(a.baseline.resolve()),'candidate':str(a.candidate.resolve()),
            'planned_matches':len(old),'identical_completed_matches':completed_equal,
            'field_differences':differences,'common_observed_lanes':len(common_old),
            'endpoint_differences':endpoint_differences,'unreadable_baseline_seeds':unknown,
            'common_observed_statistics':{'baseline':describe(common_old),'candidate':describe(common_new)},
            'note':'Missing endpoints remain missing in their own batches. Comparisons use only endpoints observed in both. Checkpoints cover selected fields and RNG, not all process memory.'}
    for label,trials in [('baseline',old),('candidate',new)]:
        values=[t['mower_frames'][i] for t in trials.values() for i in (0,2,4) if t['mower_frames'][i] is not None]
        report[label+'_summary']={'completed_matches':sum(t['status']=='all_mowers_triggered' for t in trials.values()),
            'errors':[{'seed':t['seed'],'frames':t['frames'],'mower_frames':t['mower_frames']} for t in trials.values() if t['status']=='native_error'],
            'observed':describe(values),'unobserved_lanes':len(trials)*3-len(values)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('baseline_summary','candidate_summary')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
