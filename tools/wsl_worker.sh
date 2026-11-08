#!/bin/sh
# Keep this worker's X sockets separate from WSLg and other projects.
set -eu
cd "$(dirname "$0")/.."
export PULSE_SERVER="unix:$PWD/.pulse/native"
if ! timeout 3 pactl -s "$PULSE_SERVER" info >/dev/null 2>&1; then
    mkdir -p .pulse
    chmod 700 .pulse
    cat > .pulse/default.pa <<EOF
load-module module-native-protocol-unix socket=$PWD/.pulse/native auth-anonymous=1
load-module module-null-sink sink_name=s6_worker
set-default-sink s6_worker
EOF
    pulseaudio --daemonize=yes --exit-idle-time=-1 --use-pid-file=no --disable-shm=yes \
        -nF "$PWD/.pulse/default.pa" --log-target="file:$PWD/.pulse/server.log"
    timeout 3 pactl -s "$PULSE_SERVER" info >/dev/null
fi
if [ "${S6_PRIVATE_X11:-0}" != 1 ]; then
    mkdir -p .wsl-x11
    chmod 1777 .wsl-x11
    exec unshare --mount --propagation private sh -c '
        mount --bind "$1" /tmp/.X11-unix
        shift
        export S6_PRIVATE_X11=1
        exec "$@"
    ' sh "$PWD/.wsl-x11" sh "$PWD/tools/wsl_worker.sh" "$@"
fi
exec .venv/bin/python "$@"
