"""Native Windows adapter for the unchanged s6 package.

The s6 sources are hashed into every result's execution fingerprint, so they
are not edited for Windows. Instead this module, loaded only on Windows:

- provides a minimal ``fcntl.flock`` replacement for s6 modules that import it;
- loads ``s6/engine.py`` with native DLL paths instead of Wine ``Z:`` paths;
- starts ``build/bridge.exe <pid>`` directly instead of through Wine;
- launches the original game suspended, disables its single-instance exit so
  several worker processes can run, and optionally places it on a hidden desktop.

Game rules, CT code, update/draw drivers and verification stay those of s6.
"""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import types

ROOT = Path(__file__).resolve().parent.parent
installed = False
_install_guard = threading.Lock()
CREATE_NO_WINDOW = 0x08000000


def _fcntl_shim():
    import msvcrt
    module = types.ModuleType('fcntl')
    module.LOCK_SH, module.LOCK_EX, module.LOCK_NB, module.LOCK_UN = 1, 2, 4, 8

    def flock(file, operation):
        fd = file if isinstance(file, int) else file.fileno()
        os.lseek(fd, 0, os.SEEK_SET)
        if operation & module.LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK if operation & module.LOCK_NB else msvcrt.LK_LOCK, 1)
        except OSError:
            raise BlockingIOError('locked') from None
    module.flock = flock
    return module


def install():
    """Patch in-memory module objects; files on disk (and fingerprints) are untouched."""
    # Workers call this concurrently; a second caller must not import the half-built s6.engine.
    with _install_guard:
        _install()


def _install():
    global installed
    if installed:
        return
    sys.modules.setdefault('fcntl', _fcntl_shim())
    import s6.memory

    def bridge_init(self, prefix, display=None):
        # On Windows the second argument carries the target process ID.
        self.proc = subprocess.Popen([str(ROOT/'build/bridge.exe'), str(int(display))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     creationflags=CREATE_NO_WINDOW)
        self.hello = self.proc.stdout.readline().strip()
        if not self.hello.startswith('OK '):
            self.proc.wait(timeout=5)
            raise RuntimeError(self.hello or 'Bridge exited')
    s6.memory.Bridge.__init__ = bridge_init

    path = ROOT/'s6/engine.py'
    source = path.read_text(encoding='utf-8')
    patched = source.replace("'Z:'+str(", "str(")
    if patched.count("str(ROOT/'build/") != 2 or "'Z:'" in patched:
        raise RuntimeError('s6/engine.py layout changed; update s6gui/winport.py')
    module = types.ModuleType('s6.engine')
    module.__file__ = str(path)
    module.__package__ = 's6'
    sys.modules['s6.engine'] = module
    exec(compile(patched, str(path), 'exec'), module.__dict__)
    import s6
    s6.engine = module
    installed = True


# --- process creation -------------------------------------------------------
from ctypes import wintypes  # noqa: E402  (module is imported on Windows only)

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


_desktop = None
_desktop_guard = threading.Lock()
DESKTOP_NAME = 'S6RunnerDesktop'


def hidden_desktop():
    global _desktop
    with _desktop_guard:
        if _desktop is not None:
            return 'WinSta0\\' + DESKTOP_NAME
        user32.CreateDesktopW.restype = wintypes.HANDLE
        desktop = user32.CreateDesktopW(DESKTOP_NAME, None, None, 0, 0x10000000, None)  # GENERIC_ALL
        if not desktop:
            raise ctypes.WinError(ctypes.get_last_error())
        _desktop = desktop
    return 'WinSta0\\' + DESKTOP_NAME


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_any_window = WNDENUMPROC(lambda hwnd, _: True)
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def post_click(hwnd, x, y):
    """Bridge's 'L x y' click, posted from this process; returns None or the error text.

    A process can use window handles of another desktop only after it has enumerated
    that desktop. bridge.exe never does, so its PostMessage to the hidden desktop fails
    silently and the loading screen never starts.
    """
    if _desktop is not None:
        user32.EnumDesktopWindows(wintypes.HANDLE(_desktop), _any_window, 0)
    position = (y << 16) | x
    for message, keys in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):  # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP
        if not user32.PostMessageW(hwnd, message, keys, position):
            return str(ctypes.WinError(ctypes.get_last_error()))
    return None


user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def _window_text(function, hwnd, size=512):
    buffer = ctypes.create_unicode_buffer(size)
    function(hwnd, buffer, size)
    return buffer.value


def message_box(pid):
    """Caption and text of a message box shown by the process (e.g. the game's FATAL ERROR), or None."""
    found = []

    def child(hwnd, _):
        if _window_text(user32.GetClassNameW, hwnd) == 'Static':
            found.append(_window_text(user32.GetWindowTextW, hwnd))
        return True

    def top(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or _window_text(user32.GetClassNameW, hwnd) != '#32770':
            return True
        found.append(_window_text(user32.GetWindowTextW, hwnd))
        user32.EnumChildWindows(hwnd, WNDENUMPROC(child), 0)
        return False
    callback = WNDENUMPROC(top)
    if _desktop is not None:
        user32.EnumDesktopWindows(wintypes.HANDLE(_desktop), callback, 0)
    if not found:
        user32.EnumWindows(callback, 0)
    return ': '.join(text for text in found if text) or None


_startup_mutex = None


def startup_mutex():
    """Named mutex letting one game at a time initialize its display, across threads and processes.

    Games creating their DirectDraw surfaces at the same moment can stop at "FATAL ERROR:
    Failed to initialize DirectDraw ... DDERR_NOEXCLUSIVEMODE" (seen with 6 workers, and with
    a video export starting during a batch).
    """
    global _startup_mutex
    with _desktop_guard:
        if _startup_mutex is None:
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            handle = kernel32.CreateMutexW(None, False, 'Local\\S6RunnerStartup')
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            _startup_mutex = handle
    return _startup_mutex


class NativeProcess:
    """Small Popen-like wrapper so the game can start suspended on a chosen desktop."""
    def __init__(self, executable, cwd, window='hidden'):
        info = STARTUPINFOW()
        info.cb = ctypes.sizeof(info)
        if window == 'hidden':
            info.lpDesktop = hidden_desktop()
        elif window == 'minimized':
            info.dwFlags = 1  # STARTF_USESHOWWINDOW
            info.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        process = PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(f'"{executable}"')
        if not kernel32.CreateProcessW(str(executable), command, None, None, False,
                                       0x4,  # CREATE_SUSPENDED
                                       None, str(cwd), ctypes.byref(info), ctypes.byref(process)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle, self.thread, self.pid = process.hProcess, process.hThread, process.dwProcessId
        self.returncode = None

    def resume(self):
        kernel32.ResumeThread(wintypes.HANDLE(self.thread))

    def poll(self):
        if self.returncode is None and kernel32.WaitForSingleObject(wintypes.HANDLE(self.handle), 0) == 0:
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(wintypes.HANDLE(self.handle), ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def terminate(self):
        if self.poll() is None:
            kernel32.TerminateProcess(wintypes.HANDLE(self.handle), 1)

    def wait(self, timeout=None):
        kernel32.WaitForSingleObject(wintypes.HANDLE(self.handle),
                                     0xFFFFFFFF if timeout is None else int(timeout*1000))
        return self.poll()

    def close(self):
        for h in (self.thread, self.handle):
            if h:
                kernel32.CloseHandle(wintypes.HANDLE(h))
        self.thread = self.handle = None


# SexyAppBase::Init exits when "PlantsVsZombiesMutex" already exists
# (553F16: cmp eax,ERROR_ALREADY_EXISTS; jne). Workers need parallel copies.
SINGLE_INSTANCE_JUMP = 0x553F1B
STARTUP_ATTEMPTS = 3

# SexyAppBase::EnforceCursor (455973..455A91) runs SetCursor(LoadCursorA(0, IDC_*)) every frame
# and discards the result. Both are win32k calls under the session-wide user lock: with 16
# workers they took ~35% of every game's main thread. quiet_cursor() keeps them but skips the
# system call when nothing changes: SetCursor with the cursor already set, and LoadCursorA of
# a shared system cursor, whose handle never changes.
SET_CURSOR_IAT = 0x6523c8
LOAD_CURSOR_IAT = 0x6523d4


def quiet_cursor(engine):
    m = engine.memory
    real_set, real_load = m.u32(SET_CURSOR_IAT), m.u32(LOAD_CURSOR_IAT)
    if not real_set or not real_load:
        raise RuntimeError('Unexpected SetCursor/LoadCursorA import slots')
    page = m.alloc(0x1000)
    last, set_slot, load_slot, cache = page+0x200, page+0x204, page+0x208, page+0x300
    code = engine.asm(f'''
        set_cursor:
            mov eax,dword ptr [esp+4]
            cmp eax,dword ptr [0x{last:x}]
            je set_done
            mov dword ptr [0x{last:x}],eax
            push eax
            call dword ptr [0x{set_slot:x}]
        set_done:
            ret 4
        load_cursor:
            cmp dword ptr [esp+4],0
            jne load_real
            mov eax,dword ptr [esp+8]
            sub eax,0x7f00
            cmp eax,0xff
            ja load_real
            mov ecx,dword ptr [eax*4+0x{cache:x}]
            test ecx,ecx
            jz load_fill
            mov eax,ecx
            ret 8
        load_fill:
            push eax
            push dword ptr [esp+12]
            push 0
            call dword ptr [0x{load_slot:x}]
            pop ecx
            mov dword ptr [ecx*4+0x{cache:x}],eax
            ret 8
        load_real:
            jmp dword ptr [0x{load_slot:x}]
    ''', page)
    load_offset = code.index(bytes.fromhex('837c240400'))  # cmp dword ptr [esp+4],0
    m.write(page, code)
    m.write(last, struct.pack('<III', 0xffffffff, real_set, real_load))
    m.write(SET_CURSOR_IAT, struct.pack('<I', page))
    m.write(LOAD_CURSOR_IAT, struct.pack('<I', page+load_offset))


class WinGameProcess:
    """Windows counterpart of s6.process.GameProcess (same startup protocol)."""
    def __init__(self, log_dir, window='hidden'):
        self.log_dir = Path(log_dir)
        self.window = window
        self.engine = self.game = None

    def __enter__(self):
        install()
        import winreg
        from s6.engine import Engine
        from s6.memory import Bridge
        from s6.table import GAME
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r'Software\PopCap\PlantsVsZombies') as key:
            winreg.SetValueEx(key, 'Is3D', 0, winreg.REG_DWORD, 0)
        userdata = Path(os.environ.get('ProgramData', r'C:\ProgramData'))/'PopCap Games/PlantsVsZombies/userdata'
        userdata.mkdir(parents=True, exist_ok=True)
        users = userdata/'users.dat'
        if not users.exists():
            name = b'S6Runner'
            users.write_bytes(struct.pack('<IHH', 14, 1, len(name))+name+struct.pack('<II', 1, 1))
        try:
            for attempt in range(1, STARTUP_ATTEMPTS+1):
                try:
                    self._start(Bridge, GAME)
                    break
                except (RuntimeError, TimeoutError):
                    self._stop_game()
                    if attempt == STARTUP_ATTEMPTS:
                        raise
            self.engine = Engine(None, self.game.pid)
            self.engine.verify_environment()
            self.engine.execute(f'mov eax,dword ptr [0x6a9ec0];call 0x554f90;movzx eax,al;'
                                f'mov dword ptr [0x{self.engine.SHARED+0x90:x}],eax')
            self.engine.display_3d = bool(self.engine.memory.u32(self.engine.SHARED+0x90))
            if self.engine.display_3d:
                raise RuntimeError('Original display setting did not take effect')
            quiet_cursor(self.engine)
            return self.engine
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _start(self, Bridge, GAME):
        """Launch the game and wait for the main menu with the profile loaded."""
        mutex = wintypes.HANDLE(startup_mutex())
        owned = kernel32.WaitForSingleObject(mutex, 120000) in (0, 0x80)  # WAIT_OBJECT_0, WAIT_ABANDONED
        try:
            self.game = NativeProcess(GAME/'PlantsVsZombies.exe', GAME, self.window)
            patch = Bridge(None, self.game.pid)
            try:
                if patch.read(SINGLE_INSTANCE_JUMP, 2) != b'\x75\x0c':
                    raise RuntimeError('Unexpected single-instance check bytes')
                patch.write(SINGLE_INSTANCE_JUMP, b'\xeb\x0c')
            finally:
                patch.close()
            self.game.resume()
            deadline = time.monotonic()+60
            click_error = None
            while time.monotonic() < deadline:
                if self.game.poll() is not None:
                    raise RuntimeError(f'Game exited during startup (code {self.game.returncode})')
                title = display = 0
                try:
                    b = Bridge(None, self.game.pid)
                    lawn = b.u32(0x6a9ec0)
                    title = lawn and b.u32(lawn+0x76c)
                    # LawnApp+0x36c: DDInterface; its red mask (+0x8) is read from the primary surface,
                    # so it is set once the step that fails in parallel startups has succeeded.
                    dd = lawn and b.u32(lawn+0x36c)
                    display = title or (dd and b.u32(dd+0x8))
                    ready = lawn and b.u32(lawn+0x82c) and b.u32(lawn+0x7fc) == 1
                    if title and b.u32(lawn+0x7fc) == 0:
                        click_error = post_click(b.u32(lawn+0x350), 190, 230)  # LawnApp+0x350: main HWND
                    b.close()
                    if ready:
                        break
                except RuntimeError:
                    pass
                if display and owned:
                    kernel32.ReleaseMutex(mutex)  # display initialized: the next game may start
                    owned = False
                if not title:
                    box = message_box(self.game.pid)
                    if box:
                        raise RuntimeError(f'Game startup failed: {box}')
                time.sleep(.2)
            else:
                raise TimeoutError('Game/profile initialization'+(f' (start click: {click_error})' if click_error else ''))
        finally:
            if owned:
                kernel32.ReleaseMutex(mutex)

    def _stop_game(self):
        if self.game:
            self.game.terminate()
            self.game.wait(5)
            self.game.close()
        self.game = None

    def __exit__(self, *_):
        if self.engine:
            try:
                self.engine.memory.close()
            except (OSError, RuntimeError, ValueError):
                pass
        self._stop_game()
        self.engine = None
