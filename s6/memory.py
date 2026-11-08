from __future__ import annotations
import os
from pathlib import Path
import struct
import subprocess
from .runtime import wine_environment


class Bridge:
    def __init__(self, prefix: Path, display=':121'):
        env = wine_environment(prefix.resolve(),display)
        root = Path(__file__).resolve().parent.parent
        self.proc = subprocess.Popen(['wine', str(root/'build/bridge.exe')], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.hello = self.proc.stdout.readline().strip()
        if not self.hello.startswith('OK '):
            self.proc.wait(timeout=5)
            raise RuntimeError(self.hello or 'Bridge exited')

    def command(self, line):
        self.proc.stdin.write(line+'\n'); self.proc.stdin.flush()
        result = self.proc.stdout.readline().strip()
        if not result.startswith('OK'):
            raise RuntimeError(f'{line[:80]}: {result or "Bridge exited"}')
        return result[2:].strip()

    def read(self, address, size):
        return bytes.fromhex(self.command(f'R {address:x} {size:x}'))

    def u32(self, address):
        return struct.unpack('<I', self.read(address,4))[0]

    def write(self, address, data):
        self.command(f'W {address:x} {data.hex()}')

    def batch(self,writes):
        records=[];size=4
        def flush():
            if records:
                payload=struct.pack('<I',len(records))+b''.join(records)
                self.command('B 0 '+payload.hex())
                records.clear()
        for address,data in writes:
            record=struct.pack('<II',address,len(data))+data
            if size+len(record)>0xf0000:flush();size=4
            records.append(record);size+=len(record)
        flush()

    def put32(self, address, value):
        self.write(address,struct.pack('<I',value&0xffffffff))

    def alloc(self, size, address=0):
        return int(self.command(f'A {address:x} {size:x}'),16)

    def thread(self, address, timeout=30000):
        result=self.command(f'T {address:x} {timeout:x}')
        wait, code = (int(x,16) for x in result.split())
        if wait != 0:
            raise RuntimeError(f'Remote thread wait={wait:x}, code={code:x}')
        return code

    def close(self):
        if self.proc.poll() is None:
            self.command('Q');self.proc.wait(timeout=5)
