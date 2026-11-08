# 当前关键状态（本文件替代历史未完成条目）

2026-10-27：机火裂火仙默认/快版各200局已完成，192正常、8异常、585条时长、15未完成；逐种子状态、帧数、路线时刻和检查点全部一致。正式 `--speed-mode fast` 已实现；2线程复用四局完整批次从201.96秒降至83.23秒（2.43倍），严格重放通过。见 [加速验收](EXPERIMENT_20261027.md)。

用户新图示阵容的200局**已经全部完成并验收**：`海魅窝高金 / 小灯双爆草 / 机魅火反仙 / 狙飘卷玉曾 / 胆阳叶魅嘴`，全0级，配置examples/five_lane_match_20261027.json。198有效、2异常整局无效，990有效路线；无替补。200份初始条件和独立重放文件全部核对通过，详见artifacts/five-lane-match-20261027/summary.md、matches.md、lane_times.csv、audit.json。**本批规则：卡死整局五路全部无效，不计时长及胜负**。本地8线程完成100局，mcp-wsl部署完成并以32线程完成另100局，任务及汇总器均exit0。无未完成后台比赛。详见 [比赛记录](FIVE_LANE_MATCH_20261027.md)。下文框架验收是更早任务记录，不用旧“当前”措辞覆盖本段。

用户目标：原引擎无前端测阵器，5×5 输入及条件，批量高速、多线程、可复现。只改五辆车全部触发才结束，不修任何原 CT bug；不提供自制寒意修复版。

## 当前已实现并核实

- 原 EXE、原 DLL、369 个核心 CT 脚本及原要求保持开启的 5995 均运行，只有 6093 的结束比较立即数由 1 改成 0。源码/机器码测试确认只有这一个规则字节变化。
- JSON CLI 支持阵容、层叠种植、经验、六种五路模式、彩蛋、精英盲盒标记、原精英标记 0/1/2、巨人标记、种子、重复次数、帧数上限和检查点。
- ThreadPoolExecutor 调度不同对局，每个工作线程独立 Wine 前缀/Xvfb/原游戏。支持自动并发、显式线程数、默认每局独立进程和 --reuse-game。
- CE 编译缓存保持原脚本和初始化顺序，多个地址布局逐字节校验。CT 分配现在尊重每条原 alloc 的完整大小，按页紧凑布局，注入区从 46.25 MiB 降到 4.36 MiB（0x45C000）；两个 0x20480 大声明不再超出预留块。11 项 unittest 全通过。
- 统一中文 locale，核验 GetACP()==936、99 个新增图像指针，4398 个运行文件逐条与原 ZIP 比较。错误码页导致 84 张中文图缺失的问题已纠正，不能归因原 CT bug。
- 原 Foley 选择、音调、通道限制、随机调用全部保留；DirectSound 样本播放状态按 app+484 计数推进，原分配器清理 GetTickCount 调用接同一设备时钟。每局清 Foley、清清理时间戳、app+484/app+838 初始设 0。C 测试覆盖时长/循环/变频/游标/停止/错误/回绕/未注册缓冲区委托。
- 关键纠正：CT 1316 绘制会写植物 DC 目标指针和 FB 标记。正式 steps / battle_steps 默认每次更新后完整执行原 DrawScreen（538EB0，manager 压栈 ret4），保留该行为。原随机禁用标记和 app+458 drawing 标记也遵循原相位。
- 原软件显示模式 Is3D=0；native/null_display.c 只在最终屏幕图像实例上替换 16 个纯像素栅格化入口，保留原 RTTI、所有源图像、上层原绘制、字体、动画等，关闭实际呈现。不会跳过 CT Draw。硬件 3D 会直接排队图形而绕开这些入口，禁止用这个 sink 配硬件模式。
- null display C 测试验证全部 16 个 x86 栈清理约定、原 RTTI 和源图像隔离。新工具 tools/test_native_devices.py 能在私有隐藏显示运行两组 C 测试，两组均通过。

## 当前真实运行证据

- artifacts/presented-hard-day：满阶白天 1000 帧，完整原 Draw+Present 快速与正常外层循环，快照和全部 128555 次 RNG 调用序列相同。
- artifacts/null-software-scenarios/report.json：六种五路模式各 2000 帧，满阶狙击/寒冰菇、新植物、屋顶花盆、彩蛋/精英/巨人均覆盖，快速软件像素 sink 与正常原外层循环（真实软件像素）全部一致。
- artifacts/final-drawn-two：2 线程复用四局，131.26 s，总吞吐 27.66×。
- artifacts/final-drawn-fresh-four：4 线程每局新进程四局，95.25 s，总吞吐 38.11×。
- artifacts/compact-four：紧凑 CT 分配后 4 线程复用四局，94.37 s，总吞吐 38.47×。
- artifacts/compact-eight：紧凑分配 8 线程复用八局，132.41 s，总吞吐 55.80×。
- 上述重叠四种子全部检查点、结束帧、五车时刻一致，结束帧 88343 / 107263 / 87770 / 79648；紧凑布局前后相同。
- artifacts/final-drawn-replay：正式 CLI 严格指纹 replay，种子 20261028，87770 帧，replay_matches=true（紧凑布局前版本）。紧凑布局后的 artifacts/compact-replay/results.json 也已通过严格 replay，当前指纹一致，结束 87770 帧。
- artifacts/mower-boundary：中文完整资源环境，前四车后 active=1，五车后 active=0。
- artifacts/empty-formation/results.json：全空阵、seed=1，正常与快速都在第 4707 帧 AV 0x462C3B、读取 0x8C5。栈包含 CT2549 小推车压植物调用，原函数读到对象应用指针 0。不加空指针修复，异常报错不计完赛。tools/check_empty_formation.py 可复现。
- BUGS.md 还记录寒意两个到期路径的代码差异、第六行辣椒结算循环、种子 0 特例、绘制写战斗字段、西瓜伤害来源分支及原作者已存在的魅惑 bug 修复脚本。代码疑点与运行确认分开。

## 最新验收与交付状态

- artifacts/compact-scenarios-6000/report.json：全部六种地图各 6000 帧正常/高速快照一致，manifest 与当前执行器一致。
- artifacts/compact-replay/results.json：当前紧凑布局版本的正式 CLI replay 通过，种子20261028，结束87770帧，当前指纹一致。
- 原生四/五车边界在当前紧凑布局版本再次通过。
- tools/profile_frames.py 的分层计时结果见 artifacts/profile-board/results.json：原更新约86.6%，原绘制约13.4%；绝大多数更新耗时位于原415920战斗更新，资源管理/音乐/图像清理的开销极少。后续不能通过跳过原游戏更新或 CT Draw 换取表面速度。
- artifacts/acceptance.json 对完整需求、当前验证和固定设备条件作映射；README、BUGS已更新。当前无未完成后台任务，不需要恢复旧工具 session。
- 已实现用户授权范围并完成现有验收；后续若新增优化或场景，应继续保留原 CT bug 并重新做相关差分，不能把旧版109.6×/121.3×算作当前速度。

## 已作废的历史结论与地址纠正

- 错误 ACP 的旧数据（包括 121.3×）无效。后续 gbk-* 的 109.6× 等速度早于补齐 Draw，也不能作为完整行为版本依据。不要恢复“只更新不绘图”的默认路径求速度。
- app vtable+34 =5512D0 MarkAllImagesDirty，manager+28=537510 MarkAllDirty，都不是绘制。
- 54BAE0 是显示/表面重初始化，不是 DrawDirtyStuff；以前那段实验说明是错的。真正原 DrawDirtyStuff 约 54C650，里面调用 DrawScreen 538EB0。
- Graphics ctor586A30 参数 ECX=image、压栈 selfGraphics；copyctor5869B0 EDI=self、压栈 source；dtor586B10 ECX=self。不要直接用未锁定/未flush的手造 Board Draw 替代完整 DrawScreen。
- 实际屏幕 DDImage vtable67238C，共51入口（含末尾额外项）；LockSurface index47 / UnlockSurface48。PolyFill3D 实际 ret32，不是另一版本源码的 ret28。
- native/observe.c 永远只观察异常，返回 CONTINUE_SEARCH，正式流程不加载。Windows 显示/资源异常不得被默认归类为原 CT bug。

## 操作约束

- 没有子 agent；不要创建，用户仅要求代码支持多线程。
- 不改原压缩包。不要杀其他项目 Xvfb:100 或其他 Wine 前缀。工具自己的 Host/GameProcess 负责回收。
- 批量和场景工具共用 .workers-s6/.pool.lock；不要同时启动。基准不要混入额外诊断负载；同机其他长期任务会影响速度。
- 修改 aa/table/compiled 前，确认没有仍待 install_table 的旧 Python 模块进程。fingerprint 会读磁盘，旧模块混新磁盘可能污染编译缓存。本轮一次诊断进程正好读到旧 Table/新 compiled，因缺 allocation_plan 直接失败、未写缓存；之后的新进程及缓存逐字节测试全部通过。
- build DLL 通过 .tmp 原子替换，避免截断已映射文件。不要重 poll 已结束的 session。
- 证据是选定状态/RNG/事件对照，不是穷举全进程证明；运行框架使用声明的 100Hz 更新+绘制和虚拟设备初始条件，不宣称任意真实设备时序完全相同。
