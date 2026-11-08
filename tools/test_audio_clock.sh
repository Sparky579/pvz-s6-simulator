#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -n "${S6_CC:-}" ]; then
    CC=$S6_CC
elif [ -x .toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix ]; then
    CC=.toolchain/root/usr/bin/i686-w64-mingw32-gcc-posix
else
    CC=i686-w64-mingw32-gcc
fi
mkdir -p build .wine-s6
"$CC" -O2 -static -masm=intel -Wl,--no-insert-timestamp tests/audio_clock_native.c -o build/test_audio_clock.exe
flock -n .wine-s6/.runner.lock env WINEPREFIX="$PWD/.wine-s6" WINEDEBUG=-all WINEARCH=win32 wine build/test_audio_clock.exe
