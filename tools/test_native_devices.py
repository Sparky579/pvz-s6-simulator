"""Compile and run both x86 device ABI/semantics checks in a private display."""
from pathlib import Path
import fcntl,os,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from s6.parallel import Host
from s6.runtime import wine_environment
from s6.table import ROOT

compiler=os.environ.get('S6_CC')
if not compiler:
 local=ROOT/'.toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix'
 compiler=str(local) if local.exists() else 'i686-w64-mingw32-gcc'
build=ROOT/'build';build.mkdir(exist_ok=True)
programs=[]
for name in ('audio_clock','null_display'):
 target=build/f'test_{name}.exe'
 subprocess.run([compiler,'-O2','-Wall','-static','-masm=intel','-Wl,--no-insert-timestamp',
                 str(ROOT/f'tests/{name}_native.c'),'-o',str(target)],check=True)
 programs.append(target)
prefix=ROOT/'.wine-s6'
with open(prefix/'.runner.lock','w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 with Host(prefix,ROOT/'artifacts/native-device-tests/logs') as host:
  for program in programs:
   subprocess.run(['wine',str(program)],env=wine_environment(prefix,host.display),check=True,timeout=30)
