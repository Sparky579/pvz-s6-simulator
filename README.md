# 植物大战僵尸 · 麦版 S6 斗蛐蛐测阵器

通过原版游戏引擎和 `S6正赛(bug寒).CT` 执行阵容对局，支持批量测阵、固定种子重放、五路存活时长统计，以及 Windows / Linux 图形刷阵和视频导出。

本仓库是完整项目的**源码整理版**，包含执行器、GUI、原生 C 桥接代码、工具、测试、示例和研究记录。原游戏、音乐、Wine 前缀、编译产物和历史对局输出需要在本地另行准备。

## 目录

| 路径 | 内容 |
| --- | --- |
| `s6/` | 原 CT 编译、游戏进程控制、批量执行、严格重放 |
| `s6gui/` | 图形刷阵、阵容预览、记录查看、视频与音效导出 |
| `native/` | Win32 桥接、音效时钟、绘图和状态观察代码 |
| `tools/` | 构建、统计、分片汇总、验证及历史诊断工具 |
| `examples/` | 可运行的阵容配置 |
| `tests/` | Python 回归测试和原生设备测试 |
| `research/` | 研究过程、CT 快照和参考源码；来源说明见相关文件 |
| `docs/DEVELOPMENT.md` | 原开发说明及历史性能记录 |

## 准备原游戏资源

程序仅支持开发时使用的原包 `麦版S6本体+ct+修改器.zip`，SHA-256 为：

```text
d3107c98113ab1c1af2f1fd36813782f290e09b4520bffc3810638146a690ab9
```

将该 ZIP 放在项目根目录，并在根目录执行：

```sh
python3 -m zipfile -e "麦版S6本体+ct+修改器.zip" original
```

解压后应有：

```text
pvz-s6-simulator/
├── 麦版S6本体+ct+修改器.zip
└── original/
    └── 麦版S6本体+ct+修改器/
        ├── PlantsVsZombies.exe
        ├── S6正赛(bug寒).CT
        ├── bass.dll
        ├── DllMain.dll
        ├── gdi42.dll
        └── ...原包内的完整资源目录
```

ZIP 和解压目录都需要保留：执行器会核对原包摘要及 4398 个运行文件。不要用其他版本游戏或 `research/ct.xml` 替代原包。

## Linux 安装与运行

需要 Python 3.10+、32 位 Wine（含 `wineserver`）、Xvfb、`zh_CN.UTF-8` locale 和 32 位 MinGW C 编译器。原游戏还需要可用的音频设备；批量运行可以使用 PulseAudio null sink。GUI 需要 Python 的 Tkinter，视频导出需要 ffmpeg 或 `imageio-ffmpeg`。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
sh tools/build_bridge.sh
python -m s6 inspect
python -m s6 run examples/basic.json --repetitions 10 --seed 123 --workers 4 --reuse-game -o artifacts/results.json
python -m s6 replay artifacts/results.json --index 0 -o artifacts/replay.json
```

构建脚本优先使用 `S6_CC`，其次使用本地 `.toolchain/` 中的编译器，最后查找 PATH 中的 `i686-w64-mingw32-gcc`。可显式指定：

```sh
S6_CC=/path/to/i686-w64-mingw32-gcc sh tools/build_bridge.sh
```

脚本构建 `bridge.exe`、`audio_clock.dll`、`observe.dll`、`null_display.dll`、`render_capture.dll` 和 `sound_log.dll`，输出到 `build/`。

GUI：

```sh
python -m pip install -r s6gui/requirements.txt
python -m s6gui
# 或 ./刷阵器.sh
```

首次启动会在本地创建独立 Wine 前缀及缓存；这些目录已加入 `.gitignore`。

## Windows 图形刷阵器

使用 Python 3.10+，安装 `s6gui/requirements.txt` 中的依赖并准备同样的原包和解压目录。还需要上面构建出的 `build/` 文件；可在 Linux / MinGW 环境构建后复制到 Windows，本源码仓库不附带预编译二进制。

系统“非 Unicode 程序的语言”需设为中文（简体），关闭 Beta UTF-8，确保 ACP 为 936。视频导出使用 PATH 中的 ffmpeg 或依赖中的 `imageio-ffmpeg`。

```bat
python -m pip install -r s6gui/requirements.txt
python -m s6gui
```

也可双击 `刷阵器.bat`。游戏默认在隐藏桌面运行，启动兼容性及 Windows 适配细节见 [原开发说明](docs/DEVELOPMENT.md)。

## 阵容与对局规则

阵容为 5 行 × 5 列，可使用植物数字 ID、空位 `null`、带初始经验的对象，或按种植顺序排列的多层列表；参见 [基本示例](examples/basic.json)。GUI 支持[植物单字简称](PLANT_CODES.md)，如 `机3000` 表示机枪、初始经验 3000。

默认 `exact` 保留原游戏绘制回调，`fast` 每帧执行原 CT 回调并省略场景绘制。原 CT 的游戏 bug 保留；唯一规则改动是结束时剩余未触发推车阈值由 `≤ 1` 改为 `= 0`。严格重放会校验原输入、执行器指纹和状态检查点。

```sh
python -m s6 run examples/basic.json --speed-mode fast --repetitions 100 --workers 4 --reuse-game -o artifacts/fast.json
python tools/run_lane_experiment.py examples/five_lane_match_20261027.json --speed-mode fast --workers 8 --lanes 1 2 3 4 5 --record-matches --output artifacts/match-run/results.json
```

逐局记录、异常处理和历史实验规则见 [原开发说明](docs/DEVELOPMENT.md) 与 [已知问题](BUGS.md)。部分历史诊断脚本依赖本机生成的 `artifacts/` 输入，使用前需先准备对应数据。

## 验证

安装基础 Python 依赖后，可先运行不需要原游戏的逐局记录测试：

```sh
python -m unittest discover -s tests -p test_match_records.py -v
```

准备完整原包后，可运行全部 Python 回归；原生设备检查还需要编译器、Wine 和初始化后的 `.wine-s6/`：

```sh
python -m unittest discover -s tests -v
python tools/test_native_devices.py
```

历史性能数据和整局验证结论保存在开发文档中，对应的大型对局输出未纳入源码仓库。
