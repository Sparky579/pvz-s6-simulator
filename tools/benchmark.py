"""Benchmark native batch throughput and check all gameplay checkpoints."""
from pathlib import Path
import argparse,json,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.table import ROOT

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('config',type=Path)
p.add_argument('--workers',type=int,nargs='+',default=[1,2,4])
p.add_argument('--reuse-game',action='store_true')
p.add_argument('--output-dir',type=Path,default=Path('artifacts/benchmark'))
a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
reference=None;report=[]
for workers in a.workers:
 output=a.output_dir/f'workers-{workers}.json'
 command=[sys.executable,'-m','s6','run',str(a.config.resolve()),'--workers',str(workers),'-o',str(output.resolve())]
 if a.reuse_game:command.append('--reuse-game')
 subprocess.run(command,cwd=ROOT,check=True)
 data=json.loads(output.read_text())
 actual=[{k:t[k] for k in ('seed','status','frames','mower_frames','checkpoints')} for t in data['trials']]
 if reference is None:reference=actual
 matches=reference==actual
 row={**data['execution'],'matches_serial_checkpoints':matches,'result':str(output.resolve())}
 report.append(row);(a.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(f'{workers} workers: {row["aggregate_speedup"]:.2f}x aggregate, same checkpoints={matches}',flush=True)
 if not matches:raise SystemExit('Worker-count determinism check failed')
