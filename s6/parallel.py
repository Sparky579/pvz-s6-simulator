"""Threaded scheduling with an isolated original game for each trial.

Wine services and the hidden display stay warm per worker. The actual game
process is fresh per trial, so CT globals, sound history, animation IDs and
unknown original cross-game state cannot depend on worker assignment.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
import fcntl
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from .compiled import load
from .process import GameProcess,initialize_prefix,start_display
from .runner import trial
from .runtime import wine_environment
from .table import ROOT


def automatic_workers():
    cpus=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else (os.cpu_count() or 1)
    available=None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):available=int(line.split()[1])*1024;break
    except OSError:pass
    memory_limit=max(1,int(available*.65)//(512*1024*1024)) if available else cpus
    return max(1,min(cpus,memory_limit))


def clone_prefix(source,target):
    if (target/'system.reg').exists():return
    temporary=target.with_name(target.name+'.preparing')
    if temporary.exists():shutil.rmtree(temporary)
    def copy_file(src,dst):
        relative=Path(src).relative_to(source)
        # Only shipped Windows binaries/fonts are immutable. Registry,
        # profiles, decoded sound caches and all other writable files are copied.
        immutable=(len(relative.parts)>2 and relative.parts[:2]==('drive_c','windows') and
                   Path(src).suffix.lower() in ('.dll','.exe','.cpl','.tlb','.nls','.fon','.ttf'))
        if immutable:
            try:os.link(src,dst);return dst
            except OSError:pass
        return shutil.copy2(src,dst)
    shutil.copytree(source,temporary,symlinks=True,copy_function=copy_file)
    os.replace(temporary,target)


class Host:
    def __init__(self,prefix,log_dir):
        self.prefix=prefix;self.log_dir=log_dir
    def __enter__(self):
        self.xvfb,self.display,self.log=start_display(self.log_dir)
        env=wine_environment(self.prefix,self.display)
        try:
            subprocess.run(['wineserver','-p'],env=env,check=True,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        except BaseException:
            self.xvfb.terminate();self.xvfb.wait(timeout=5);self.log.close();raise
        return self
    def __exit__(self,*_):
        try:
            subprocess.run(['wineserver','-k'],env=wine_environment(self.prefix),
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            subprocess.run(['wineserver','-w'],env=wine_environment(self.prefix),
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        finally:
            self.xvfb.terminate();self.xvfb.wait(timeout=5);self.log.close()


def run_batch(config,workers=1,log_dir=None,on_result=None,reuse_game=False):
    if workers<0:raise ValueError('workers must be zero (automatic) or positive')
    count=config.data['repetitions']
    workers=min(count,automatic_workers() if workers==0 else workers)
    directory=ROOT/'.workers-s6';directory.mkdir(exist_ok=True)
    log_dir=Path(log_dir or ROOT/'artifacts/logs')
    lock=open(directory/'.pool.lock','w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close();raise RuntimeError('Another batch owns the worker pool') from None
    results=[None]*count;pending=queue.Queue();stop=threading.Event()
    for i in range(count):pending.put(i)
    output_guard=threading.Lock()
    started=time.monotonic()
    try:
        # Build/verify at most once before threads start; workers only relink.
        load(version=config.data['version'])
        prefixes=[directory/f'worker-{i:02d}' for i in range(workers)]
        missing=[p for p in prefixes if not (p/'system.reg').exists()]
        if missing:
            base=ROOT/'.wine-s6';base.mkdir(exist_ok=True)
            with open(base/'.runner.lock','w') as base_lock:
                try:fcntl.flock(base_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise RuntimeError('The base Wine prefix is in use') from None
                initialize_prefix(base)
                subprocess.run(['wineserver','-k'],env=wine_environment(base),
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                for prefix in missing:clone_prefix(base,prefix)

        def work(worker):
            worker_logs=log_dir/f'worker-{worker:02d}'
            def next_index():
                if stop.is_set():return None
                try:return pending.get_nowait()
                except queue.Empty:return None

            def initialize(engine):
                engine.install_table(version=config.data['version'])
                engine.instrument_mowers();engine.clock_audio()
                engine.discard_pixels()

            def run_one(engine,index):
                seed=(config.data['seed']+index)&0xffffffff
                item=trial(engine,config,seed,stop)
                item['worker']=worker
                with output_guard:
                    results[index]=item
                    if on_result:on_result(index,item)

            with Host(prefixes[worker],worker_logs) as host:
                index=next_index()
                while index is not None:
                    with GameProcess(prefix=host.prefix,log_dir=worker_logs/f'process-{index:06d}',
                                     display=host.display,keep_server=True) as engine:
                        initialize(engine)
                        run_one(engine,index)
                        if reuse_game:
                            index=next_index()
                            while index is not None:
                                run_one(engine,index)
                                index=next_index()
                    if not reuse_game:index=next_index()
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='s6-worker') as pool:
            futures=[pool.submit(work,i) for i in range(workers)]
            try:
                for future in as_completed(futures):future.result()
            except BaseException:
                stop.set();raise
    finally:lock.close()
    return results,{'workers':workers,'wall_seconds':time.monotonic()-started,
                    'scheduler':'threads',
                    'game_lifecycle':'reuse original process per worker' if reuse_game else
                                     'fresh original process per trial; warm Wine host'}
