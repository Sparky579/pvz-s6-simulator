# 2026-10-27 机火裂火仙统计与加速

## 最新结果：原版与快版各 200 局已完成

- 原计划均为种子 `20261027..20261226`，未补样本。默认模式结果在 `artifacts/ji-huo-lie-huo-xian-200-20261027/fresh_results.json`；独立快版结果在 `artifacts/ji-huo-lie-huo-xian-fast-200-20261027/results.json`。
- 两批均为 **192 局正常结束、8 局异常、585 条已观测时长、15 条未完成**。逐种子比较 `status/frames/mower_frames/checkpoints` 全部相同，包括未读到内存的种子 `20261208`。其根因仍未单独证明。
- 585 条对应路线时长差均为 0；已观测均值 **1275.4384615384615 秒**，中位数 **1315.67 秒**，两版相同。192 局正常结束的逐段状态摘要也全部一致；这不是任意阵容、全部进程字段的等价证明。
- 比较工具：`python3 tools/compare_lane_experiments.py BASELINE CANDIDATE --output REPORT`。已生成 `artifacts/speed-investigation/lane-comparison.json`。两批各有 `statistics.json/statistics.txt/lane_times.csv`，600 行 CSV 中未完成终点留空。
- 快版 200 局为 12 线程、每局新原游戏进程，完整墙钟 **1330.365 秒（22:10.37）**。旧基准分段执行，其 `2936.259` 秒只是最后 153 局的执行段，不能据此计算整个 200 局的加速倍数。两批运行还混有诊断负载。
- 同步四方案测试：同一原战斗种子，预热至 90000 帧，四进程屏障同步后测量 10000 帧；原绘制 **6.856 秒**，只省屏幕锁 **6.852 秒**，只保留 CT 棋盘回调 **2.545 秒**，两项合并 **2.470 秒**，墙钟加速 **2.776 倍**。四方案前后战斗快照相同。该测试仍与 200 局批次并行，CPU 时间分别 12.30/5.59/4.06/1.71 秒，不能把 CPU 时间比直接当墙钟速度比。文件 `artifacts/speed-investigation/drawing-ablation/report.json`。
- 较早独立计时窗口 `heavy-baseline` 对 `heavy-fast-drawing` 为 **4.427 倍**；同机负载不同，作为补充观察。正式 CLI 相同四种子、2线程、每线程复用两局，包含加载与清理的完整批次：exact **201.9597 秒**、fast **83.2259 秒**，**2.42665 倍**。四局所有检查点、结束帧和推车时刻一致，正式快版严格重放种子20261027通过。见 `artifacts/speed-investigation/cli-comparison.json` 和 `cli-fast-replay/results.json`。

## 正式实现及验证

- `Config.speed_mode` 为 `exact|fast`，默认 exact；`s6 run --speed-mode fast`、JSON 字段、`inspect` 和严格 `replay` 均记录模式。原 EXE/CT/DLL 和资源没有改动，原音效及 RNG 路径保持。
- `Engine.set_fast_drawing` 将 Board::Draw 换成调用原 `41A2A0` 的小回调（包含完整 CT1316），并省最终屏幕锁。所有原更新仍每帧执行。每局 prepare 前恢复完整绘制，资源加载/开场走原路径，准备完成后再启用快版。
- 已验证六种地图各 6000 帧快照相同：`artifacts/speed-investigation/six-map-validation/report.json`。正式快模式在同一游戏进程连续两局的全部检查点和结束帧与原基准一致：`production-reuse/results.json`，结束帧 198200 / 188347。
- 12 项 unittest 已通过，新增 Unicorn 用例核对原函数调用的寄存器与栈约定、快模式开关恢复，配置覆盖默认/快版/非法值。
- `tools/run_lane_experiment.py --speed-mode fast` 使用正式实现，并保留失败种子。200 局快版验证使用同字节的历史 `--fast-drawing` 原型；原记录的执行指纹没有追改成新执行器。正式 CLI 与原型通过相同输入及检查点核对。
- 原 CT3584 的速度累乘动画死循环，以及原 Attachment 第17项越界，均在恢复原四车规则和原正常外层循环时复现；详细证据已写入 `BUGS.md`。种子68/74错误窗口、61208退出未单独归因。不修原 bug。

下方为历史过程记录；其中“正在运行”、工具 session、待办和旧指纹叙述仅适用于当时，以上方最新结果为准。

## 历史过程记录

用户要求：第1/3/5路从左至右机枪40、火炬22、裂荚28、火炬22、仙人掌26，第2/4路全空，200局、600条路时长统计。默认白天mode1、零经验自然升级、S6bug原CT。时长按开战至该路原小推车首次触发，100帧/秒。种子20261027至20261226。

用户后续明确：**保留原定200局，不补样本；必须诊断卡死是原版已有还是测阵器引入**。未观测路线单列，不能填0或把截止时间当触发时间，不能伪称600条路都已得到完整时长。

路径：artifacts/ji-huo-lie-huo-xian-200-20261027/。
- 正式200局：fresh_results.json，由tools/run_lane_experiment.py运行，每局新游戏，5并发。当前工具session84091，恢复时以实际poll为准。已完成的9个重叠种子与原复用批次所有检查点和推车事件一致。
- results.json：最初复用批次，10局后因超时中止，只用于诊断，不纳入最终统计。
- seed-20261034-fresh.json：独立新进程复现第159998帧动画更新卡死，mower_frames=[93837,6831,-1,6228,63132]；第3路未触发。mAnimTime=26066044.0，mAnimRate=122510409728.0，循环EIP471C9B..471CB2，反复减1写回float不改变数值。尚不能单凭这个断言原规则也会卡。
- 该对象reanimationType21，对照原进程参数表6A9EF0，路径reanim/Zombie.reanim，为普通僵尸动画。
- seed-20261034-normal.json：正在原正常外层循环、真实软件绘图、仍五车结束规则下对照，预计需约27分钟真实时间；session50592。
- seed-20261034-original-four-mowers.json：恢复原CT四车结束阈值的对照已完成：第93837帧（938.37秒）active=0、正常结束，推车事件[93837,6831,-1,6228,63132]。因此字面原四车规则同一种子不会走到159998帧，而是提前结束。工具session68932已结束。
- 后续需要从异常前帧追踪Zombie动画速率变大的原代码/CT写入，区分潜在数值bug与适配器引入。不要修CT或注入防卡死补丁。
- 统计工具tools/lane_statistics.py：默认完整性严格校验，用户已选择保留200局，因此最终用 --allow-censored 导出600行CSV（未完成留空并标记），输出总体已观测均值、各行均值、未完成数；不得把已观测均值说成600路线完整均值。
- 所有新代码均在tools/或examples/，没有修改正式s6/native实现或CT，当前原执行器指纹不变。


## 续接状态（以正式文件实时计数为准）

- 原5并发阶段已保存47个完成的原定种子；为利用恢复的内存，取消当时在途对局并使用同一种子重启，新增 --resume 按原计划缺失种子映射，不替换任何异常种子。
- 正式当前运行：tools/run_lane_experiment.py ... --workers 12 --resume .../fresh_results.json，session91742。原47个结果已保留，当前约98/200。脚本已验证200种子唯一不重不漏。旧session84091已被SIGINT结束，不要再poll；最早49148也已结束。
- seed20261034正常原外层循环 session50592已结束：同于159998帧、同一471C9B..471CB2循环、同样推车数组卡住；动画时间26066044.0、速率122510409728.0，与高速完全一致。
- 根因已定位原CT3584“僵尸速度”：针对type0x1E且byte72=1（精英倭瓜/梦咯），每次进入原动画速度计算，原表代码将Zombie+34速度乘2.6并写回。原函数会重复调用，速度指数增长。只观察的rate-trace/results.json捕获第159995..159998帧速度3445597 ->8958553 ->23292236 ->60559812 ->157455504 ->409384288 ->1064399104 ->2767437568，动画速率最终122510409728。原动画每次减1存回float26066044会四舍五入成原值，循环不退出。
- 四车对照：seed34四车在93837帧正常结束；seed42恢复四车阈值仍于144312帧相同动画循环卡住，只踩三车，因此不是必须改成五车才出现。其原正常外层循环+原四车规则的进一步对照仍在跑，session1775，worker15，输出seed-20261042-original-normal-four-mowers.json。
- 新发现另一异常类别：seed50第151408帧AV631F7C，原Attachment分配过程405660调用memset写出错；正被单独诊断，**不要把它未经验证就归为原CT bug**。已做被动VEH观察，rate-trace-20261050/results.json有精确栈。此例没有同时出现精英倭瓜速度爆炸，须单独归因。
- seed50原正常外层循环+原四车规则对照：session15364，worker13；输出seed-20261050-original-normal-four-mowers.json，约25分钟真实时间。
- seed50高速原函数写入追踪+被动异常+Attachment池头轨迹正在重跑：session72327，worker14；输出rate-trace-20261050/results.json（本次会增加attachment_history和attachment_header_at_end）。前一次39302已完成，不再poll。
- 浮点环境额外核对artifacts/fpu-environment/results.json：原游戏、开CT、加载音效设备、加载像素设备、加载异常观察器后控制字均0x027F，没有精度/舍入控制字变化。
- 当前所有诊断前缀13/14/15均在正式12线程的0..11之外。不要杀其余项目进程。正式文件/CT/ZIP/s6/native未作修改，所有新代码只在tools和examples，因此执行指纹不变。
- 统计工具已验证有0/7/600个缺失时都输出600行CSV，缺失终点留空，均值/中位数独立计算一致。最终用 --allow-censored，明确“已观测路线均值/中位数”，单列异常与缺失数，不把停止帧冒充推车时长。用户已明确不补样本。


## 进一步已闭环的动画卡死诊断

- 原四车阈值 + 原正常外层循环（真实软件绘图）seed20261042已在第144312帧同一471CAD位置卡死，推车数组[-1,6738,-1,5106,137123]，当时只触发3路。此证据排除五车规则是必要条件，也排除快速驱动是必要条件；原CT3584速度累乘本来就存在。session1775已结束，不再poll。
- seed20261034正常外层与快速同于159998帧卡住，动画mAnimTime与mAnimRate均逐位相同。session50592已结束。
- seed50附件异常的第二次追踪完成，session72327已结束：Attachment池容量1024、高水位162、活跃21，free-list-head却成为0x44808B00（按float为1028.34375），是空闲链表受损，不能归为简单“池满”或尚未证明的其他原因。
- 正在追踪native405581追加附件时的16项边界及调用栈：tools/trace_attachment_corruption.py，session35019，worker14，输出attachment-trace-20261050/results.json。
- seed50原四车规则+正常外层循环的独立对照session15364仍在跑，worker13。
- 正式批量session91742仍在跑，约130/200；文件fresh_results.json为权威实时计数。前47例复用已完成结果不是warmup，是正式fresh阶段结果；最初results.json复用10例才是排除的诊断数据。


## 200局已完成与新提速任务

用户新明确授权：无需100%随机数一致，只需表现及统计基本一致，希望明显提速；保留当前200局作为基准，新模式独立验证，不能混用结果。默认初验目标均值、中位数偏差约5%以内。

基准完成：fresh_results.json已有全部200个种子，192局正常结束、8局异常。585条时长、15条未完成。statistics.json/statistics.txt/lane_times.csv已生成：已观测均值1275.44秒(21:15.44)，中位1315.67秒(21:55.67)，各路195/193/197条。session91742已结束，不再poll。

所有旧正常循环诊断均已结束：seed50原四车+正常外层同在151408帧原631F7C访问异常，crash副本native-normal-last-crash.txt显示运行26:24、F4线程，证明这一类也能在原正常流程出现。
附件边界追踪attachment-trace-20261050/results.json：第151389帧原405581追加时count=16，调用者原532333；附件内只有16项×0x30字节，后续写越过数组边界覆盖+300/+304/+308元数据。151408帧空闲链表头被float1028.34375覆盖，随后原分配器越界清零AV。池高水位162、容量1024，不是池满。session35019已结束。
尚未单独归因：seed61208原进程退出ERR5，所有路线时刻不可读取；其3条计为未知，没有补样本。其余8次异常列表在正式JSON，后续诊断注意区别，不要把所有都无证据归成同一种。

速度原型均在tools/，没有改s6/native生产代码或DLL，故旧基准指纹保持。不要执行tools/build_bridge.sh覆盖生产DLL，直到准备好版本化新模式。
- tools/fast_audio_clock.c + fast_audio_device.py：健康虚拟设备绕过原GetStatus、缓存元数据，编译build/fast_audio_clock.dll。测得仅1.014×，100000帧状态相同，收益太小，不应作为主优化。
- tools/fast_null_display.c：NoLock原型DLL已编译，但主绘制原型直接改已克隆的屏幕vtable47，无需该DLL。
- tools/fast_drawing.py是关键原型：替换Board::Draw vtable656CA8+68为小回调，pushad保存寄存器，EDI=Graphics*，压栈Board*，直接调用原41A2A0。该函数包含完整CT1316，每帧执行目标DC/FB等写入；跳过原场景/Reanimation绘制。屏幕图像LockSurface47返回false，所有源图像仍原锁，DrawScreen照常跑，surfaceLocked只控制Unlock。
- 原型安装在prepare之后；intro仍完整原绘制。仅新进程模式已测试；复用时必须prepare前恢复原Board.Draw和屏幕Lock，prepare后再启用。
- 100000帧中后段实测：heavy-baseline 90000预热+10000测量=4.4029秒，draw占67.44%；heavy-fast-audio4.3419秒；heavy-fast-drawing0.9946秒，draw占1.21%。三者100000帧state_data完全相同。约4.43×单段提速，需后续整局/分布复核。
- NativeOverlay ABI：41A2A0从stack+4取Board*到EDX，EDI输入Graphics*，自己读App到EAX；ret4。Board::Draw thiscall ECX=Board、stack+4=Graphics、ret4。原型代码pushad;mov edi,[esp+36];push ecx;call41a2a0;popad;ret4。
- 线程采样tools/thread_cpu_probe.c/build/thread_cpu_probe.exe：停在主线程门时无后台忙等，排除了“后台键盘死循环”猜测，不能据此随意停线程。原音效路径不是当前主收益。

当前在跑六地图精确快照对照：tools/validate_fast_drawing.py，实际工具session见最近工具输出。占workers0..2与pool.lock；等完成后运行同一200种子的fast-drawing独立批量（tools/run_lane_experiment.py已添加--fast-drawing，并在resume时校验drawing_profile）。预计快很多，需比对结束帧/路线时刻/均值/中位/异常，不是只看速度。
后续若验证通过，再把快模式做成正式可选profile（默认精确模式保留），更新CLI/config/manifest/replay与README。无需追求seed逐位一致，但当前原型有望保留。
