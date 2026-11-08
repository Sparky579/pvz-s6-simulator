> 原开发说明的存档。文中的预编译文件、原游戏、历史测试输出和本机部署环境未随源码上传；安装请以根目录 README 为准。此处性能与实测结论为历史记录。

# 麦版 S6 原引擎测阵器

以压缩包中的 `PlantsVsZombies.exe`、DLL、资源和 `S6正赛(bug寒).CT` 为执行核心。
通过 Wine 在隐藏的 X 服务中运行原游戏，命令行输入阵容并批量推进原游戏主线程；没有自制前端。

已接通完整对局、种子复跑、编译缓存和多线程批量运行。固定中文 Win32 码页 936，启动时验证原资源完整。默认 `exact` 保留完整原绘制回调并丢弃最终像素输出；可选 `fast` 进一步省略原场景绘制，每帧仍执行原 CT 绘制回调及其中修改狙击目标的代码。两种模式都按 100 Hz 执行原游戏更新。

按用户最新要求，保留原 CT 的全部游戏 bug，不提供自行修复寒意的分支。
唯一规则改动是正赛剩余未启动推车的结束阈值由 `≤ 1` 改为 `= 0`。

## 运行

当前开发环境为 Linux + 32 位 Wine。需要 `wine`、`Xvfb`、Python 3.10+、系统的 `zh_CN.UTF-8` locale 和 MinGW 32 位 C 编译器。
本工作目录已有解压后的原包和本地编译工具链；原始压缩包不作修改。

还需要可用的音频设备后端，批量时可以是私有 PulseAudio null sink。丢弃 PCM 输出仍保留健康的原 DirectSound 缓冲区；缺少音频设备会改变原 Foley 的随机抽样。`mcp-wsl` 的配置见下文。

```sh
python3 -m pip install -r requirements.txt
sh tools/build_bridge.sh
python3 -m s6 inspect
python3 -m s6 run examples/basic.json --repetitions 10 --seed 123 --workers 0 -o artifacts/results.json
# 尽量提高大量对局的吞吐：复用每个线程的游戏进程和资源缓存
python3 -m s6 run examples/basic.json --repetitions 100 --workers 4 --reuse-game -o artifacts/fast.json
# 新加速模式，也支持多线程和进程复用
python3 -m s6 run examples/basic.json --speed-mode fast --repetitions 100 --workers 4 --reuse-game -o artifacts/faster.json
python3 -m s6 replay artifacts/results.json --index 0 -o artifacts/replay.json
```

`replay` 自动使用结果中保存的速度模式，校验原包、执行器指纹和逐段状态摘要；有差异时返回非零状态，不将差异当作成功。历史结果保留其原指纹，升级执行器后不会伪装成当前版本接受重放。
运行时使用本目录自己的 `.wine-s6` 和 `.workers-s6/worker-*`。每个工作线程有独立的 Wine 环境、隐藏显示和原游戏进程；单局内部仍按原顺序执行。线程只并行调度不同对局，不拆开原游戏的对象更新。结果按试验编号排序，种子不随任务分配改变。

`--workers 0` 按 CPU 亲和性和可用内存自动选择数量，并限制为对局数；`--workers 1` 串行，其他正整数指定线程数。默认每局新建原游戏进程；`--reuse-game` 每个线程只加载一次，局间销毁原棋盘、恢复 CT 全局初值、清空原 Foley 槽、重设种子和初始计数，再建原棋盘。已通过混合阵整局对照；涉及未覆盖的跨局隐藏状态时，可用默认独立进程模式复核。

## 阵容和条件

见 [examples/basic.json](../examples/basic.json)。`formation` 必须正好 5 行 × 5 列：从上到下、从左到右，列为原场地最左侧五列。

每格可写植物十进制 ID、`null`、`{"id": 7, "xp": 3000}`，或按种植顺序排列的多层列表。
经验交给原 CT 自己升级，不直接改等级而跳过升级事件。重叠与非法组合也按原种植函数处理。

| 字段 | 含义 |
| --- | --- |
| `version` | 固定为 `s6-bug`，对应原始 bug 寒意 CT |
| `speed_mode` | 默认 `exact`；`fast` 保留每帧原 CT 回调，省略原场景绘制 |
| `seed` | 32 位种子；原 RNG 的 0 种子特殊处理也保留 |
| `repetitions` | 次数；第 i 次使用 `seed + i`，按 uint32 回绕 |
| `mode` | 五路生存模式：1 白天、2 黑夜、5 屋顶、6/7/10 对应困难模式 |
| `max_frames` | 单局最大推进帧数；达到上限与五车全踩分开统计 |
| `easter` | `original`、`disabled`、`forced`，对应 CT 原有标记 |
| `elite` | `original`、`forced`，设置 CT 的盲盒精英标记 `701820` |
| `elite_marker` | 原 CT 的精英初始标记 `701200`：0、1 或 2；与盲盒标记分开，后续仍由原脚本处理 |
| `giant` | 原 CT 的巨人标记，0 或 1 |
| `checkpoint_every` | 状态检查点间隔，默认 1000 帧 |

常用 ID：0 豌豆、3 坚果、5 寒冰射手、7 双发、14 寒冰菇、23 高坚果、25 路灯、36 大蒜、40 机枪、42 曾哥、44 冰瓜。
包内说明给出的新增植物为 49 爆坚、51 飘飘、52 反双、76 藤、77 幽、78 奶、79 逆。数字均为十进制。

默认启用原 CT 的 `3562/s6` 核心组全部 369 个脚本，以及原表注明“保持开启”的 `5995/100%平分经验传递`。
出怪间隔、盲盒概率、经验、寒意、每 1200 帧辣椒等均执行原脚本，不另外实现一份近似模型。

## 输出与验证

JSON 包含配置、原压缩包及 4398 个运行文件的校验摘要、设备/码页初始条件、种子、结束原因、总帧数、五路推车触发时刻、计算耗时和逐段状态摘要。
摘要覆盖植物、僵尸、子弹的一组稳定战斗字段、狙击目标和锁定标记、原 RNG 全状态和推车事件，尚不等于全进程状态证明。`speedup` 是单局战斗推进速度；`execution.aggregate_speedup` 是累计游戏秒数除以总墙钟秒数，包含加载与清理耗时。原包异常会报错，不计为正常完赛，已知问题见 [BUGS.md](../BUGS.md)。

```sh
python3 -m unittest discover -s tests -v
python3 tools/test_native_devices.py
python3 tools/check_mower_boundary.py
python3 tools/validate_execution.py --frames 5000 --normal --software --discard-pixels --skip-present --output artifacts/device-check/results.json
python3 tools/validate_scenarios.py --frames 6000 --workers 3 --discard-pixels
```

回归测试覆盖核心脚本无遗漏、标签大小写、原址补丁边界、原声明内存分配、快版回调的寄存器及栈约定和切换恢复，以及唯一规则变化确实只有一个阈值字节。新增的逐局记录测试还验证并列胜出、卡死整局五路无效及统计排除规则。两组原生 C 检查分别验证音频设备语义和全部 16 个像素入口的 x86 栈约定。
`validate_execution.py` 从独立游戏进程比较高速推进、原外层循环及真实/无声输出。六场景的长对照结果见 6000 帧报告（`artifacts/compact-scenarios-6000/report.json`，本机历史输出）。其他 `state_probe`、`trace_frames` 等脚本保留作历史诊断，部分有意不启用音效时钟，不能将它们与正式运行的初始条件混为一谈。

## 加速与复现方式

- 原包通过 ANSI 文件接口读取中文素材。执行器强制中文 locale，核验目标游戏 `GetACP()==936` 和 99 个原新增图像槽；不允许把缺资源的启动当作成功。4398 个运行文件逐一与原 ZIP 校验，额外混入的运行文件也会报错。
- 原 CT 编译结果缓存到 `.cache-s6`，在多个独立地址布局逐字节核对后才使用。370 条记录重定位约 2.4 毫秒；补丁批量传入，保持原先后顺序及初始化调用顺序。按 CT 原声明保留完整分配空间，注入区从 46.25 MiB 降至 4.36 MiB。
- 高速路径逐帧调用原总更新函数和 `DrawScreen`，省去等待实际帧间隔；原 CT 绘制中的战斗状态修改全部继续执行。使用原软件绘图选项，只替换最终屏幕图像的 16 个像素栅格化方法，省去实际像素写入和呈现；源图像、字体、动画和上层绘制回调仍按原顺序处理。不会以大步长近似碰撞、攻击或状态计时。
- `fast` 在上述驱动中，将棋盘绘制改为直接执行原 `41A2A0`（包含完整 CT `1316`），省去场景和角色画面绘制；最终屏幕也省去无像素输出所不需要的表面锁。音效、原 RNG 和更新顺序保持原路径。资源加载、开局准备仍使用完整绘制，进程复用时先恢复再切换。六种地图各 6000 帧快照已与默认路径一致；这不是任意阵容全部隐藏字段的等价证明。
- 原音效是否播放完毕会影响 Foley 的随机抽样。设备适配器按原样本长度、频率、循环和游戏帧推进播放状态，保留原音效选择、音调、通道限制及其 RNG 调用，省去实际 PCM 播放。
- 每局把原 `LawnApp+0x838`、`SexyAppBase+0x484` 计数设为 0，再开始准备。舞王会读取前者；只固定种子而不固定这些初始条件会随加载时间改变结果。
- 上述设备时钟与初始状态都记入执行指纹。目标是固定可复现实验环境；真实声卡和任意加载时序下的声音状态本来可能不同。
- 显示实验条件固定为每次原更新后执行一次原 `DrawScreen`，100 Hz。逐段摘要和场景对照验证的是这些声明条件下的行为；不代表已经穷举所有对象字段或任意真实设备的时序。

完整资源、中文码页环境下的当前实测如下，总吞吐包含启动、加载与清理耗时。

新 `fast` 模式在机火裂火仙相同四种子、2 线程、每线程复用两局的正式 CLI 测试中，将完整批次从 **201.96 秒降为 83.23 秒，约 2.43 倍**；包含加载与清理。四局所有检查点、结束帧和推车事件一致，快版严格重放也通过。见 整局计时（`artifacts/speed-investigation/cli-comparison.json`，本机历史输出） 和 快版重放（`artifacts/speed-investigation/cli-fast-replay/results.json`，本机历史输出）。相同 200 种子的独立原型对照也全部一致，见 逐种子比较（`artifacts/speed-investigation/lane-comparison.json`，本机历史输出）。速度随阵容及同机负载变化。

下表是此前默认 `exact` 模式的混合阵测试，不与上段不同阵容的吞吐直接相除。

| 线程 | 对局数 | 进程复用 | 墙钟秒数 | 总吞吐 |
| --- | --- | --- | --- | --- |
| 2 | 4 | 是 | 131.26 | 27.7× |
| 4 | 4 | 否 | 95.25 | 38.1× |
| 4 | 4 | 是 | 94.37 | 38.5× |
| 8 | 8 | 是 | 132.41 | 55.8× |

重叠四种子的全部检查点、结束帧和推车时刻一致，结束帧为 88343 / 107263 / 87770 / 79648。原始结果见 八线程结果（`artifacts/compact-eight/results.json`，本机历史输出）、四线程结果（`artifacts/compact-four/results.json`，本机历史输出）、四线程独立进程结果（`artifacts/final-drawn-fresh-four/results.json`，本机历史输出）。速度受阵容和同机其他任务负载影响。

此前 121.3× 等测试使用了错误的 ANSI 环境；之后 109.6× 的测试又早于补齐原 CT 绘制回调。这些历史速度不能当作当前完整行为版本的性能，相关战果和等价结论也不能混入上述结果。

可重复跑基准并自动比较不同线程数量的结果：

```sh
python3 tools/benchmark.py examples/basic.json --workers 1 2 4 --reuse-game
```

## 机火裂火仙 200 局

配置见 [ji_huo_lie_huo_xian_135.json](../examples/ji_huo_lie_huo_xian_135.json)：第 1/3/5 路均为机枪、火炬、裂荚、火炬、仙人掌，第 2/4 路留空。白天、零初始经验自然升级；时长从开战到本路首次触发原推车。

原定 200 个种子的默认模式结果已完成：192 局正常结束、8 局原生异常，600 条计划路线中得到 585 条时长、15 条未完成，没有补种子。已观测时长均值 **1275.44 秒（21:15.44）**、中位数 **1315.67 秒（21:55.67）**；这不是 600 条完整时长的均值。见 统计表（`artifacts/ji-huo-lie-huo-xian-200-20261027/statistics.txt`，本机历史输出）、600 行 CSV（`artifacts/ji-huo-lie-huo-xian-200-20261027/lane_times.csv`，本机历史输出）。

需要记录异常后继续跑完种子计划时，使用实验驱动；普通 `s6 run` 遇到原生异常会报错停止。

```sh
python3 tools/run_lane_experiment.py examples/ji_huo_lie_huo_xian_135.json --speed-mode fast --workers 12 --output artifacts/lane-experiment/results.json
python3 tools/lane_statistics.py artifacts/lane-experiment/results.json --allow-censored
```

`--resume` 只补跑同一计划中尚未保存的种子，不替换已记录的异常，且要求配置和执行指纹一致。卡死诊断与原版对照证据见 [BUGS.md](../BUGS.md)，性能与快版对照详见 [本轮记录](../research/EXPERIMENT_20261027.md)。

## 单字阵容与逐局比赛记录

[植物单字表](../PLANT_CODES.md) 和 [机器可读映射](../plant_codes.json) 保留用户约定。`tools/formation_from_codes.py` 可将五行单字阵容转换为数值配置；`空` 表示空位，简称不包含等级。

本轮图示阵容为 `海魅窝高金 / 小灯双爆草 / 机魅火反仙 / 狙飘卷玉曾 / 胆阳叶魅嘴`，全零经验。完整条件见 [配置](../examples/five_lane_match_20261027.json)。用户对本轮指定：**卡死整局五路全部无效，不计入胜负或时长，不补局**。不要将这个规则追写到此前保留部分观测的机火裂火仙基准中。

```sh
python3 tools/run_lane_experiment.py examples/five_lane_match_20261027.json --speed-mode fast --workers 8 --lanes 1 2 3 4 5 --record-matches --output artifacts/match-run/results.json
```

每局开战前保存完整数值配置、实际种子、初始经验、原包/执行器指纹、机器与 Wine 版本、实际初始计数器、选定状态及 RNG；结束后单独生成严格 `s6 replay` 可读取的 `matches/局号-seed-种子/replay.json`。每完成一局原子更新 `matches.md`、`matches.csv` 和结果 JSON。最长原推车时刻对应胜出路，同帧并列。这里只保存重放输入与状态，不预先生成视频。

两台机器可用 `--shards 2 --shard-index 0` 和 `--shards 2 --shard-index 1` 分别执行原种子计划的奇数/偶数局，种子不随线程分配改变。`tools/collect_match_shards.py` 校验配置、原输入和执行器指纹、分片归属及种子唯一性，再增量更新合并文档；不接受重复种子。

`mcp-wsl` 已部署在 `/root/s6-simulator`，使用项目 `.venv`、复制并校验的原包及辅助二进制。通过现有 SSH 别名进入后，可用 `sh tools/wsl_worker.sh -m s6 run ...`；此包装器在独立 mount namespace 中使用项目私有 X 套接字，并检查/启动私有 PulseAudio null sink。当前配置使用 root 和 `unshare`，不修改其他项目的 WSLg 套接字。远程首局严格重放的全部 188 个检查点已通过。

`tools/run_background.py --job-dir DIR -- COMMAND ...` 可在 SSH 断开后继续执行，保存 PID、输出及退出状态。本轮远程分片为 32 线程，进展见 实时逐局文档（`artifacts/five-lane-match-20261027/matches.md`，本机历史输出）。

## 图形刷阵器（Windows / Linux）

```sh
python3 -m pip install -r s6gui/requirements.txt
python3 -m s6gui          # 或双击 刷阵器.bat（Windows）/ 运行 ./刷阵器.sh（Linux）
```

- **阵容**：5 行文字，用[单字简称](../PLANT_CODES.md)，空位写 `空`，字后接数字为该株初始经验（如 `机3000`），行间换行或 `/`。停止输入半秒后画出阵容图：不启动游戏，直接用原包图片拼成（`s6gui/sprites.py`：每株取原 reanim 定义里待机动画的第一帧，按 CT 在植物创建时的做法隐藏 `awake*`/`easter`/`special` 皮肤轨道；植物→reanim 的对应关系从 S6 的 EXE 表里读，包括 ZZZ* 扩展）。CT 额外画的等级盾牌、泥点等不在图里。
- **刷阵**：选择模式、起始种子、局数（0 = 一直刷到点停止）、线程数和其他原 CT 标记。每完成一局就在列表追加一行：五路各自撑住的时间、对局时长（第二名失败的时刻）、胜者。原生异常整局标为无效。每局保存为 `artifacts/gui/<时间>/matches/局号-seed-种子.json`，与 `s6 replay` 格式相同；“打开记录”也能载入以前的 GUI 记录和 `matches/*/replay.json`。
- **导出视频**：在列表中选一局，选择场景（原模式背景、斗蛐蛐地图0–5、原版白天/黑夜/屋顶背景），以及第二名失败后是否继续到第一名失败。导出以 exact 原绘制重放该局，每个检查点比对保存的状态摘要和推车时刻，不一致就中止。25 fps。视频带原游戏音效，不含背景音乐：渲染时 `build/sound_log.dll` 记录原 Foley 的每次播放、停止、音量、声像和音调变化及对应战斗帧，事后用游戏自己解码的采样混音。默认只混入植物音效；推车、僵尸叫声/啃食和波次提示默认不混入，需要时可勾选。场景只替换 `Board::DrawBackground` 选中的背景图，不改变战斗；左下角“斗蛐蛐：泳池”字样由 CT 绘制，不随场景改变。

`s6gui/` 不修改 `s6/` 的任何文件，所以执行器指纹不变，已有记录照样可以严格重放和渲染。Linux 上每个线程使用独立的 `.workers-gui/worker-*` 前缀，预览用 `preview`，导出用 `render`，不与命令行批量任务的 `.workers-s6` 冲突。

**Windows**：直接运行原 EXE，不需要 Wine，`build/` 里已编译好的 PE 文件可以直接使用。需要满足以下条件：

- 32 或 64 位 Python 3.10+。
- 系统区域设为中文（简体），即“非 Unicode 程序的语言”为中文，且不勾选 Beta UTF-8；原包的中文素材依赖 ACP 936，启动时会检查。
- 有 ffmpeg：放进 PATH，或者用 `imageio-ffmpeg` 自带的。

游戏默认在隐藏桌面中运行。如果在你的机器上起不来，可以设环境变量 `S6_WINDOW=minimized` 或 `S6_WINDOW=visible` 再试。为了多线程同时运行，适配层会在进程启动前跳过原游戏的单实例退出（`553F1B` 处的 jne 改为 jmp）；这处只在启动时执行，不涉及对局逻辑。开局那一下“点击开始”由 Python 进程直接 `PostMessage` 给隐藏桌面上的游戏窗口（`winport.post_click`）：一个进程要先枚举过那个桌面，才能用上面的窗口句柄，`bridge.exe` 的 `L` 命令没做这一步，在隐藏桌面上会静默失败。已在 Windows 11 上实测刷阵可用。

Windows 上另有三处只在内存里生效的适配（都在 `s6gui/winport.py`，不改 `s6/`，指纹不变）：

- 多个游戏同时初始化 DirectDraw 会有一个停在 “FATAL ERROR: Failed to initialize DirectDraw … DDERR_NOEXCLUSIVEMODE”。启动用命名互斥量 `Local\S6RunnerStartup` 排队（跨线程、跨进程，刷阵和导出同时进行也排），排到 DDInterface 读出主表面像素格式（`[[LawnApp+0x36C]+0x8]`）为止，每个约 0.6 秒；启动时出现错误框会立刻带上框里的文字报错，并重开游戏，最多 3 次。
- 原版 `SexyAppBase::EnforceCursor`（455973–455A91）每帧调用 `SetCursor(LoadCursorA(0, IDC_*))`，这两个都是要拿会话级 win32k 锁的系统调用，16 线程时占每个游戏主线程约 35%。`quiet_cursor` 改写这两个导入表槽位：光标没变就不再调用 `SetCursor`，系统光标句柄缓存。实测 16 线程每局从 34× 提到 73×，32 局的推车时刻和全部 3066 个检查点摘要与不改时逐一相同。
- 在 i9-14900HX（32 线程）上，每个游戏约占 350 MB 内存，总吞吐随线程数基本线性：12 线程约 950×、16 线程约 1180×、24 线程约 1680× 实时。线程数按空闲内存取，留出 2 GB 左右。导出是单个游戏的软件渲染（精确模式约 4.6× 实时），不随线程数变快。
