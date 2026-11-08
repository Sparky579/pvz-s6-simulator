# 研究进度与继续工作入口

历史研究记录。当前实现、纠正和已通过的验收以 [CURRENT.md](CURRENT.md)、[README.md](../README.md) 为准；下文旧版速度和旧“未通过”条目不能当作当前状态。

## 当前任务要求

无自制前端；5×5 阵容和条件输入；批量高速运行原游戏；五路推车全部触发才结束；可复现。
用户最新明确要求：原 CT 完整保留，游戏 bug 一个都不修，只记录。此前关于寒意修复选项的要求已被这条覆盖。

## 已完成的基础

- 原始压缩包只读，解压在 `original/麦版S6本体+ct+修改器`。
- 核心 CT 369 脚本全编译，额外打开原表要求的 5995。默认只修改 6093 的结束阈值 1 -> 0。
- `native/bridge.c`：Wine 内跨进程读写、分配、线程/上下文查询和隐藏原窗口开始点击。
- `s6/engine.py`：在 LawnApp::Update 入口 452650 的原游戏主线程执行命令；原函数前六字节跳板。
- `s6/runner.py`：创建原生生存棋盘、原函数种植、设置原 CT 条件、逐帧推进并记录五路推车时刻。
- `s6/aa.py`：CE 本地标签区分大小写、16 进制默认数值、#十进制、原址短跳转及前向标签长编码。
- JSON CLI、文件/执行器指纹、检查点及失败即非零的 replay 校验已接通。

## 已有运行证据

- 25 双发阵两次 5000 帧批量测试通过。
- 混合阵已多次完成所有五路推车触发；曾测得约 33～60 倍游戏时间速度。
- 6 项 unittest 通过；覆盖所有核心脚本、唯一一字节规则修改、大小写标签、短原址补丁边界等。
- 混合阵单类诊断：路灯、高坚果、坚果、双发的原生 20 帧运行通过。

## 未通过的关键验收，不能标为完成

1. 同种子复现：冷/热准备会有额外 RNG 调用。`tools/state_probe.py` 记录 4 次准备；第 3、4 次相同，第 1、2 次不同。
2. 正常外层循环 vs 高速路径：`tools/compare_frames.py` 比较相同热状态起点的 500 帧。起点一致，终点的攻击倒计时、子弹标记、RNG 不一致。
3. 需要解释这些差异并使高速路径保留原包逻辑，不能把更小的一组绿色测试视为完整等价。
4. 还未做足够多植物/僵尸、升级/彩蛋/寒意、屋顶/黑夜和碰撞等场景的差分验证。

## 当前追踪工具

- `Engine.normal_frames()`：临时放行原外层循环更新/绘制，运行指定帧数后重新停在主线程边界。
- `Engine.trace_rng()`：在 5A9A37 原 RNG 返回前记录值、战斗帧和调用栈前五个 dword；只观察，不替换返回值。
- `tools/trace_frames.py`：从相同热状态比较 100 帧高速与正常模式，输出第一个 RNG 调用差异。
- 日志/进程/exec session 只能当定位线索；恢复工作时须重新检查具体句柄是否还活着，不能仅凭本文件重启或判定在跑。

## 函数与数据已核对

- 452650 LawnApp::Update；其内部会递增 838 MJ 时钟、清理对象、调用 SexyAppBase::Update -> 54B980 -> 539140 WidgetManager 更新。
- 44F560：ESI=LawnApp，push 是否载入、push mode，创建原关卡。
- 44F380：EDI=LawnApp，销毁旧棋盘；不是 ESI 参数。
- 44F6B0：ESI=LawnApp，移除选卡界面并开始原关卡。
- 40D120：EAX=row，push imitater、type、col、Board，原种植函数。
- 5AF420：ECX=seed，调用全局 MT 种子初始化；全局状态 75A910，长度 9C4。
- 453C30 创建 reanimation；453C80 创建 particle system，不能混用。
- 4735E0 是 reanimation definition 的按需加载路径，参数 type 与 boolean 均压栈。
- Reanimation 全局表：6A9EE8 指向每项 0x10 的定义状态表；6A9EF0 指向每项 0x0C 的参数表。

## 参考来源

- [CE 7.5 Auto Assembler 源码](https://github.com/cheat-engine/cheat-engine/blob/7.5/Cheat%20Engine/autoassembler.pas)：本地 label 的 tokencheck/replacetoken 是精确大小写比较；前向 label 预留较长指令。
- [CE 7.5 汇编器源码](https://github.com/cheat-engine/cheat-engine/blob/7.5/Cheat%20Engine/Assemblerunit.pas)：SHORT / LONG 和相对跳转编码。
- [AvZ 原引擎调用封装](https://github.com/vector-wlc/AsmVsZombies/blob/master/src/avz_asm.cpp)：函数地址与调用约定参考；均继续用当前 EXE 反汇编核实。
- [AvZ 跳帧流程](https://github.com/vector-wlc/AsmVsZombies/blob/master/src/avz_script.cpp)：普通总循环和跳帧中的战斗循环、对象清理顺序。

## 2026-10-26 最新更新（以上历史“未通过”条目以本节为准）

用户追加要求：尽可能加速，并支持多线程；仍明确不修任何原 CT bug。

已实现：

- `s6/compiled.py`：经四个地址布局核对的原机器码重定位缓存。370 条记录约 2.4 ms 重定位；原 CT 顺序、3 个初始化调用顺序保持。
- `native/bridge.c`：补丁批量写入、标准输出缓冲、手工十六进制收发，减少跨进程及格式化开销。
- `s6/parallel.py`：ThreadPoolExecutor 调度多局，每个线程独立 Wine 前缀和 Xvfb。默认每局独立游戏进程；可 `--reuse-game` 复用每个线程的进程和资源。按试验编号固定种子和结果顺序。
- `--workers 0` 按 CPU 和内存自动选择，显式正数可指定并发。
- `native/audio_clock.c`：原 Foley 逻辑不变；设备状态按样本、音调及原游戏时钟推进，默认不实际输出 PCM。保留原随机调用与 API 错误。
- 每局清空原 Foley 槽及样本历史，并把 app+838 / app+484 设为初始条件 0。原舞王函数 52DF90 会读取 app+838；此前约 4500 / 14000 帧之后的分歧由此解释。

验证证据：

- 7 项 unittest 通过（含编译缓存与不同真实地址布局的原编译结果逐字节比较）。
- 独立 C 设备测试覆盖播放长度、循环、变频、停止、游标、错误、DWORD 时钟回绕及未注册缓冲区委托。
- `artifacts/clock-normalized-serial/results.json` 与 `clock-normalized-parallel/results.json`：种子 20261026 / 20261027，所有战斗检查点、结束帧与五车事件一致。结束帧 82244 / 108406。
- `artifacts/reuse-long/results.json` 同样与独立进程结果一致。正式 CLI `replay` 对第二个种子通过（`verified-replay/results.json`）。
- 同进程同种子完整长局复跑两次均在 82244 帧结束，所有检查点一致（`clocked-full-replay/data.json`）。
- 原正常外层循环 vs 高速，以及无声 vs 物理输出的 1000 帧状态逐字段一致（`normalized-normal/results.json`）。
- 更长正常绘制测试在约 2298 帧出现原 Fatal Error 对话框：AV 0x588A10，EAX=0，原指令 `mov eax,[eax+24]`。截图在 `artifacts/normal-stall/screen.png`；暂未归因原 CT 还是资源初始化，不修改原函数，也不把它当成已通过的 5000 帧差分。
- 五车边界原引擎测试：四辆触发后 active=1，第五辆触发后 active=0（`mower-boundary/result.json`）。

速度（同机同混合阵，包含启动/清理）：

- 两局串行独立进程：累计 1906.50 游戏秒 / 82.45 墙钟秒，23.1×。
- 两局双线程：46.95 墙钟秒，40.6×。
- 两局串行复用：56.63 秒，33.7×；第二局战斗本身 68.8×。
- 四局四线程：累计 3652.08 游戏秒 / 51.33 秒，71.1×。

继续入口：

1. 读取当前所有运行 session 的实际结果，不假定上述句柄仍活着。
2. 扩展多植物/多地图/升级/彩蛋的语义差分；调查正常绘制的空图像访问，区分原 bug 与接入问题。不要修原 CT。
3. `tools/benchmark.py` 可重复跑不同线程数量，并逐检查点核对结果。跨局复用需持续对照独立进程。
4. 原引擎和原 CT 不代表自制 AA 适配器及设备适配已得到全状态等价证明；没有证据前不宣称所有原包行为都已穷举验证。

补充：八局八线程运行完成，60.62 秒墙钟，总吞吐 121.3×；与四线程重叠四种子全部检查点一致。双线程复用四局 63.11 秒、57.9×，与四线程全部一致。音频 C 单元验证可用 `sh tools/test_audio_clock.sh` 重跑。

黑夜寒意阵追加验证：无声高速与物理输出高速 1000 帧全部快照一致；正常绘制在第 9 帧进入错误对话框，不能算正常/高速对照通过。仍不修改原绘制或寒意函数。源码与正式执行器指纹自 `reuse-long` / `verified-replay` 起没有行为改动，后续只增补工具、文档和构建器查找方式。


## 完整绘制与紧凑分配版本验收

已纠正中文资源缺失及遗漏CT绘制状态的问题。正式路径保留原全部更新和DrawScreen，仅省略最终像素输出与实际等待。注入区按原alloc完整声明缩到4.36MiB。11项Python回归和两组原生C检查通过；六种五路模式各6000帧与正常循环一致。四个完整对局种子在2/4/8线程、独立/复用进程、紧凑分配前后均一致，当前严格replay也通过。八线程八局总吞吐55.8×，含加载清理。原空阵异常在快/正常路径同于4707帧复现，只记录不修复。完整映射见artifacts/acceptance.json。
