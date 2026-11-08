from __future__ import annotations
import fcntl
import os
from pathlib import Path
import select
import struct
import subprocess
import time
from .engine import Engine
from .memory import Bridge
from .runtime import wine_environment
from .table import ROOT, GAME


def initialize_prefix(prefix):
    prefix=Path(prefix).resolve();prefix.mkdir(parents=True,exist_ok=True)
    if not (prefix/'system.reg').exists():
        env=wine_environment(prefix,WINEARCH='win32')
        subprocess.run(['xvfb-run','-a','wineboot','-u'],env=env,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
    userdata=prefix/'drive_c/ProgramData/PopCap Games/PlantsVsZombies/userdata'
    userdata.mkdir(parents=True,exist_ok=True)
    users=userdata/'users.dat'
    if not users.exists():
        name=b'S6Runner'
        users.write_bytes(struct.pack('<IHH',14,1,len(name))+name+struct.pack('<II',1,1))


def start_display(log_dir):
    Path(log_dir).mkdir(parents=True,exist_ok=True)
    readfd,writefd=os.pipe()
    log=open(Path(log_dir)/'xvfb.log','w')
    process=subprocess.Popen(['Xvfb','-displayfd',str(writefd),'-screen','0','1024x768x24','-nolisten','tcp'],
                              pass_fds=(writefd,),stdout=log,stderr=log)
    os.close(writefd)
    try:
        if not select.select([readfd],[],[],10)[0]:raise TimeoutError('Xvfb startup')
        display=':'+os.read(readfd,32).decode().strip()
    except BaseException:
        process.terminate();process.wait(timeout=5);log.close();raise
    finally:os.close(readfd)
    return process,display,log


class GameProcess:
    """Own the private Wine prefix, hidden X server, game, and bridge lifecycle."""
    def __init__(self,prefix=None,log_dir=None,display=None,keep_server=False,software_display=True):
        self.prefix=Path(prefix or ROOT/'.wine-s6').resolve()
        self.log_dir=Path(log_dir or ROOT/'artifacts').resolve()
        self.engine=None;self.game=None;self.xvfb=None
        self.display=display;self.keep_server=keep_server
        self.software_display=software_display

    def __enter__(self):
        self.log_dir.mkdir(parents=True,exist_ok=True)
        self.prefix.mkdir(parents=True,exist_ok=True)
        self.lock=open(self.prefix/'.runner.lock','w')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This private Wine prefix is already in use') from None
        try:
            initialize_prefix(self.prefix)
            if self.display is None:
                self.xvfb,self.display,self.xlog=start_display(self.log_dir)
            env=wine_environment(self.prefix,self.display,WINEDEBUG=os.environ.get('S6_WINEDEBUG','-all'),
                                 LP_NUM_THREADS='2')
            if self.software_display is not None:
                subprocess.run(['wine','reg.exe','add',r'HKCU\Software\PopCap\PlantsVsZombies',
                                '/v','Is3D','/t','REG_DWORD','/d',str(int(not self.software_display)),'/f'],
                               env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            self.glog=open(self.log_dir/'game.log','w')
            self.game=subprocess.Popen(['wine',str(GAME/'PlantsVsZombies.exe')],cwd=GAME,env=env,
                                       stdout=self.glog,stderr=self.glog)
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if self.game.poll() is not None:raise RuntimeError('Game exited during startup; see game.log')
                try:
                    b=Bridge(self.prefix,self.display)
                    lawn=b.u32(0x6a9ec0)
                    ready=lawn and b.u32(lawn+0x82c) and b.u32(lawn+0x7fc)==1
                    if lawn and b.u32(lawn+0x7fc)==0 and b.u32(lawn+0x76c):
                        # Let the original loading screen accept its own start
                        # button only after resource loading is complete.
                        b.command('L 190 230')
                    b.close()
                    if ready:break
                except RuntimeError:pass
                time.sleep(.2)
            else:raise TimeoutError('Game/profile initialization')
            self.engine=Engine(self.prefix,self.display)
            self.engine.verify_environment()
            self.engine.execute(f'mov eax,dword ptr [0x6a9ec0];call 0x554f90;movzx eax,al;'
                                f'mov dword ptr [0x{self.engine.SHARED+0x90:x}],eax')
            self.engine.display_3d=bool(self.engine.memory.u32(self.engine.SHARED+0x90))
            if self.software_display is not None and self.engine.display_3d==self.software_display:
                raise RuntimeError('Original display setting did not take effect')
            return self.engine
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def __exit__(self,*_):
        if self.engine:
            try:self.engine.memory.close()
            except (OSError,RuntimeError):pass
        if self.game and self.game.poll() is None:
            self.game.terminate()
            try:self.game.wait(timeout=5)
            except subprocess.TimeoutExpired:self.game.kill();self.game.wait()
        if self.game and not self.keep_server:
            subprocess.run(['wineserver','-k'],env=wine_environment(self.prefix),
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        if self.xvfb:
            self.xvfb.terminate();self.xvfb.wait(timeout=5)
        for attr in ('glog','xlog','lock'):
            if hasattr(self,attr):getattr(self,attr).close()
