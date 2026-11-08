"""Start the original game on Linux (private Wine prefix + hidden X server) or Windows."""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys
import threading

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == 'win32'
_prefix_guard = threading.Lock()

if WINDOWS:
    from . import winport
    winport.install()


def automatic_workers():
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
    available = None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1])*1024
                break
    except OSError:
        pass
    if WINDOWS:
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            available = status.ullAvailPhys
        except (OSError, AttributeError):
            pass
    memory_limit = max(1, int(available*.65)//(512*1024*1024)) if available else cpus
    return max(1, min(cpus, memory_limit))


def requirements():
    """Human-readable list of missing runtime prerequisites."""
    missing = []
    if WINDOWS:
        import ctypes
        if ctypes.windll.kernel32.GetACP() != 936:
            missing.append('Windows 系统区域需设为 中文(简体)（非 Unicode 程序语言），且不勾选 Beta UTF-8；原包中文素材依赖 ACP 936')
    else:
        for tool in ('wine', 'wineserver', 'Xvfb'):
            if not shutil.which(tool):
                missing.append(f'缺少 {tool}')
    for name in ('bridge.exe', 'audio_clock.dll', 'null_display.dll', 'render_capture.dll'):
        if not (ROOT/'build'/name).exists():
            missing.append(f'缺少 build/{name}（Linux 上运行 sh tools/build_bridge.sh）')
    return missing


def window_mode():
    """Windows only: hidden (separate desktop, default), minimized or visible."""
    return os.environ.get('S6_WINDOW', 'hidden')


class Slot:
    """One isolated place to run original game processes (one per worker thread)."""
    def __init__(self, name, log_dir):
        self.name = name
        self.log_dir = Path(log_dir)
        self.host = None

    def __enter__(self):
        if WINDOWS:
            return self
        import fcntl
        import subprocess
        from s6.parallel import Host, clone_prefix
        from s6.process import initialize_prefix
        from s6.runtime import wine_environment
        self.prefix = ROOT/'.workers-gui'/self.name
        with _prefix_guard:
            if not (self.prefix/'system.reg').exists():
                base = ROOT/'.wine-s6'
                base.mkdir(exist_ok=True)
                with open(base/'.runner.lock', 'w') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise RuntimeError('基础 Wine 前缀 .wine-s6 正被其他任务使用') from None
                    if not (base/'system.reg').exists():
                        initialize_prefix(base)
                        subprocess.run(['wineserver', '-k'], env=wine_environment(base),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    self.prefix.parent.mkdir(exist_ok=True)
                    clone_prefix(base, self.prefix)
        self.lock = open(self.prefix/'.slot.lock', 'w')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError(f'{self.prefix} 正被另一个刷阵器使用') from None
        # This private prefix is ours now; clear a server left by an abruptly killed run.
        subprocess.run(['wineserver', '-k'], env=wine_environment(self.prefix),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        try:
            self.host = Host(self.prefix, self.log_dir)
            self.host.__enter__()
        except BaseException:
            self.host = None
            self.lock.close()
            raise
        return self

    def __exit__(self, *exc):
        if self.host:
            try:
                self.host.__exit__(*exc)
            finally:
                self.host = None
                self.lock.close()

    @contextmanager
    def game(self, log_dir=None):
        log_dir = Path(log_dir or self.log_dir)
        if WINDOWS:
            with winport.WinGameProcess(log_dir, window_mode()) as engine:
                yield engine
        else:
            from s6.process import GameProcess
            with GameProcess(prefix=self.prefix, log_dir=log_dir, display=self.host.display,
                             keep_server=True) as engine:
                yield engine


def initialize(engine, version='s6-bug', five_mowers=True):
    """Same per-process setup as s6.parallel.run_batch."""
    engine.install_table(version=version, five_mowers=five_mowers)
    engine.instrument_mowers()
    engine.clock_audio()
    engine.discard_pixels()


def game_path(path):
    """A host path as the game process sees it."""
    path = Path(path).resolve()
    return str(path) if WINDOWS else 'Z:'+str(path).replace('/', '\\')


def shared_dir():
    if not WINDOWS and Path('/dev/shm').is_dir():
        return Path('/dev/shm')
    import tempfile
    return Path(tempfile.gettempdir())


def ffmpeg():
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError('找不到 ffmpeg：请安装 ffmpeg 并加入 PATH，或 pip install imageio-ffmpeg') from None
