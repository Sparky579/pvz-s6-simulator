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
mkdir -p build
"$CC" -O2 -Wall -static -Wl,--no-insert-timestamp native/bridge.c -o build/bridge.tmp.exe
"$CC" -O2 -Wall -shared -static-libgcc -masm=intel -Wl,--kill-at,--no-insert-timestamp native/audio_clock.c -o build/audio_clock.tmp.dll
"$CC" -O2 -Wall -shared -static-libgcc -Wl,--kill-at,--no-insert-timestamp native/observe.c -o build/observe.tmp.dll
"$CC" -O2 -Wall -shared -static-libgcc -masm=intel -Wl,--kill-at,--no-insert-timestamp native/null_display.c -o build/null_display.tmp.dll
"$CC" -O2 -Wall -shared -static-libgcc -Wl,--kill-at,--no-insert-timestamp tools/render_capture.c -o build/render_capture.tmp.dll
"$CC" -O2 -Wall -shared -static-libgcc -Wl,--kill-at,--no-insert-timestamp s6gui/native/sound_log.c -o build/sound_log.tmp.dll
mv build/sound_log.tmp.dll build/sound_log.dll
mv build/render_capture.tmp.dll build/render_capture.dll
mv build/null_display.tmp.dll build/null_display.dll
mv build/observe.tmp.dll build/observe.dll
mv build/bridge.tmp.exe build/bridge.exe
mv build/audio_clock.tmp.dll build/audio_clock.dll
