"""Merge disjoint machine assignments and refresh the per-match document."""
from pathlib import Path
import argparse,copy,fcntl,json,statistics,subprocess,time
from match_records import atomic_json,write_documents,winner


def merge(directory):
    sources=[]
    for label in ('local','remote'):
        path=directory/label/'results.json'
        if path.exists():sources.append((label,json.loads(path.read_text())))
    if not sources:return None
    first=sources[0][1]
    result={k:copy.deepcopy(first[k]) for k in ('manifest','config','config_sha256')}
    combined={};origins={}
    for label,data in sources:
        if any(data[k]!=result[k] for k in ('manifest','config','config_sha256')):
            raise ValueError(f'{label}: execution fingerprint or initial conditions differ')
        origins[label]={k:data[k] for k in ('assignment','runtime_environment','execution') if k in data}
        for raw in data['trials']:
            seed=raw['seed'];index=(seed-result['config']['seed'])&0xffffffff
            if index>=result['config']['repetitions'] or seed in combined:
                raise ValueError(f'Duplicate or unplanned seed {seed}')
            assignment=data['assignment']
            if index%assignment['shards']!=assignment['shard_index']:
                raise ValueError(f'{label}: seed outside its assigned shard')
            t=copy.deepcopy(raw)
            for field in ('initial_conditions_file','replay_file'):
                if field in t:t[field]=label+'/'+t[field]
            t['source_machine']=label;combined[seed]=t
    result['trials']=sorted(combined.values(),key=lambda t:(t['seed']-result['config']['seed'])&0xffffffff)
    result['sources']=origins
    valid=[t for t in result['trials'] if t.get('valid_for_statistics',False)]
    summary={'planned':result['config']['repetitions'],'recorded':len(combined),'valid_matches':len(valid),
             'invalid_matches':len(combined)-len(valid),
             'policy':'A native error invalidates all five lanes. No replacement seeds. Longest mower time wins; ties share a win.',
             'by_lane':{}}
    for lane in range(1,6):
        values=[t['mower_frames'][lane-1]/100 for t in valid]
        wins=sum(lane in winner(t) for t in valid)
        summary['by_lane'][str(lane)]={'valid_samples':len(values),'wins_including_ties':wins,
            'win_rate':wins/len(valid) if valid else None,
            'mean_seconds':statistics.fmean(values) if values else None,
            'median_seconds':statistics.median(values) if values else None}
    result['summary']=summary
    atomic_json(directory/'results.json',result);atomic_json(directory/'summary.json',summary)
    write_documents(directory,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--remote-source',help='SSH rsync source of the remote shard directory, ending with /')
    p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=float,default=5)
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    if a.interval<1:raise ValueError('Polling interval must be at least one second')
    lock=(a.directory/'.collector.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another collector already updates this experiment')
    previous=None;last_error=None
    while True:
        if a.remote_source:
            remote=a.directory/'remote';remote.mkdir(exist_ok=True)
            try:
                sync=subprocess.run(['rsync','-a','--protect-args','--exclude','fresh-logs-*',
                                     '--exclude','*.tmp','--',a.remote_source,str(remote)+'/'],
                                    text=True,capture_output=True,timeout=60)
                error=sync.stderr if sync.returncode else None
            except subprocess.TimeoutExpired:error='SSH sync timed out; saved local results remain available'
            if error and error!=last_error:
                print('Remote sync pending:',error.strip()[-400:],flush=True)
            last_error=error
        result=merge(a.directory)
        if result:
            summary=result['summary'];count=summary['recorded']
            if count!=previous:
                print(f'{count}/{summary["planned"]}: valid={summary["valid_matches"]}, invalid={summary["invalid_matches"]}',flush=True)
                previous=count
            if count==summary['planned'] or not a.watch:break
        elif not a.watch:raise SystemExit('No shard results found')
        time.sleep(a.interval)


if __name__=='__main__':main()
