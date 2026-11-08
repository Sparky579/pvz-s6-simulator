#!/bin/sh
# Linux 启动图形刷阵器（需 wine、Xvfb、zh_CN.UTF-8 locale）
cd "$(dirname "$0")" && exec python3 -m s6gui "$@"
