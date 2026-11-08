"""Run a worker independently of SSH and retain its PID, log, and exit status."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,subprocess,sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job-dir',type=Path,required=True)
    p.add_argument('--supervise',action='store_true')
    p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();command=a.command[1:] if a.command[:1]==['--'] else a.command
    if not command:raise ValueError('A worker command is required')
    a.job_dir=a.job_dir.resolve();a.job_dir.mkdir(parents=True,exist_ok=True)
    if not a.supervise:
        with (a.job_dir/'output.log').open('ab') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--supervise',
                '--job-dir',str(a.job_dir),'--',*command],stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        (a.job_dir/'supervisor.pid').write_text(str(proc.pid)+'\n')
        print(f'Started PID {proc.pid}; {a.job_dir}/output.log',flush=True);return
    status={'command':command,'started_utc':datetime.now(timezone.utc).isoformat()}
    (a.job_dir/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    try:status['exit_code']=subprocess.run(command).returncode
    except Exception as exc:status.update(exit_code=1,error=repr(exc))
    status['finished_utc']=datetime.now(timezone.utc).isoformat()
    (a.job_dir/'status.json').write_text(json.dumps(status,indent=2)+'\n')


if __name__=='__main__':main()
