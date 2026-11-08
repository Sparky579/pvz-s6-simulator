"""Continuous multi-threaded matches; every finished match becomes a replayable record."""
from __future__ import annotations
from concurrent.futures import CancelledError
from datetime import datetime
import itertools
import json
import os
from pathlib import Path
import threading
import time
from .platform import ROOT, Slot, initialize


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, path)


def summarize(trial):
    """Lane seconds, match length (runner-up loss) and winners for one trial."""
    frames = trial.get('mower_frames') or [None]*5
    complete = trial.get('status') == 'all_mowers_triggered' and all(f is not None for f in frames)
    known = sorted(f for f in frames if f is not None)
    return {'lanes': [None if f is None else f/100 for f in frames],
            'duration': known[-2]/100 if complete else None,
            'winners': [i+1 for i, f in enumerate(frames) if complete and f == known[-1]],
            'valid': complete}


def load_record(path):
    """A GUI record or any `s6 replay`-compatible single-trial result (e.g. matches/*/replay.json)."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not data.get('trials'):
        raise ValueError(f'{path}: 没有对局')
    return data


class Brusher:
    """Run trials seed, seed+1, ... on `workers` threads until `count` (0 = until stopped)."""
    def __init__(self, data, workers, count, reuse, emit, directory=None):
        from s6.config import Config
        self.config = Config.parse({**data, 'repetitions': 1})
        self.workers, self.count, self.reuse, self.emit = workers, count, reuse, emit
        self.stop_event = threading.Event()
        self.counter = itertools.count()
        self.guard = threading.Lock()
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.directory = Path(directory or ROOT/'artifacts/gui'/stamp)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='s6-brusher', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def next_index(self):
        if self.stop_event.is_set():
            return None
        with self.guard:
            index = next(self.counter)
        return index if not self.count or index < self.count else None

    def _run(self):
        from s6.compiled import load
        from s6.runner import manifest
        started = time.monotonic()
        try:
            self.emit('log', '校验原包与执行器指纹…')
            self.manifest = manifest(self.config.data['speed_mode'])
            load(version=self.config.data['version'])
            atomic_json(self.directory/'session.json', {'config': self.config.data, 'manifest': self.manifest,
                                                       'workers': self.workers, 'reuse_game': self.reuse})
            self.emit('log', f'开始：{self.workers} 线程，记录目录 {self.directory}')
            threads = [threading.Thread(target=self._guarded_worker, args=(w,), daemon=True)
                       for w in range(self.workers)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        except Exception as exc:
            self.stop_event.set()
            self.emit('error', f'{type(exc).__name__}: {exc}')
        finally:
            self.emit('done', time.monotonic()-started)

    def _guarded_worker(self, worker):
        try:
            self._worker(worker)
        except CancelledError:
            pass
        except Exception as exc:
            self.stop_event.set()
            self.emit('error', f'线程 {worker+1}: {type(exc).__name__}: {exc}')

    def _worker(self, worker):
        from s6.runner import trial
        logs = self.directory/'logs'/f'worker-{worker:02d}'
        with Slot(f'worker-{worker:02d}', logs) as slot:
            index = None
            while True:
                if index is None:
                    index = self.next_index()
                if index is None:
                    return
                self.emit('worker', worker, f'启动游戏（第 {index+1} 局）')
                with slot.game(logs/f'process-{index:06d}') as engine:
                    initialize(engine, self.config.data['version'])
                    while index is not None:
                        seed = (self.config.data['seed']+index) & 0xffffffff
                        self.emit('worker', worker, f'第 {index+1} 局 种子 {seed}')
                        ok = self._one(engine, trial, index, seed, worker)
                        index = None
                        if not ok or not self.reuse:
                            break  # a native failure leaves the process untrusted: restart it
                        index = self.next_index()
                self.emit('worker', worker, '空闲')

    def _one(self, engine, trial, index, seed, worker):
        started = time.monotonic()
        try:
            item = trial(engine, self.config, seed, self.stop_event)
            ok = True
        except CancelledError:
            raise
        except Exception as exc:
            # Recorded, never corrected; the whole match is invalid (as in run_lane_experiment).
            item = {'seed': seed, 'status': 'native_error', 'error': repr(exc), 'frames': None,
                    'mower_frames': [None]*5, 'checkpoints': [], 'game_seconds': None, 'speedup': None,
                    'wall_seconds': time.monotonic()-started}
            try:
                item['frames'] = engine.memory.u32(engine.ELAPSED)
                item['mower_frames'] = [t if t >= 0 else None for t in engine.mower_times()]
            except Exception:
                pass
            ok = False
        item['worker'] = worker
        from s6.config import Config
        config = Config.parse({**self.config.data, 'seed': seed, 'repetitions': 1})
        record = {'manifest': self.manifest, 'config': config.data, 'config_sha256': config.digest,
                  'trials': [item], 'gui': {'index': index+1, 'summary': summarize(item)}}
        path = self.directory/'matches'/f'{index+1:05d}-seed-{seed}.json'
        atomic_json(path, record)
        with self.guard:
            with open(self.directory/'results.jsonl', 'a', encoding='utf-8') as f:
                f.write(json.dumps({'index': index+1, 'seed': seed, 'status': item['status'],
                                    'mower_frames': item['mower_frames'], 'file': path.name},
                                   ensure_ascii=False)+'\n')
        self.emit('result', path, record)
        return ok
