# 原框架参考源码

本目录文件来自 [Patoke/re-plants-vs-zombies](https://github.com/Patoke/re-plants-vs-zombies) 的 `main`，用于研究图像/窗口/控件调用关系。它是另一个版本的逆向工程源码，不直接作为麦版函数地址依据，也不编译替代游戏逻辑。当前执行器所有调用地址与 ABI 仍需用用户 EXE 的反汇编核对。

- [SexyAppBase.cpp](https://github.com/Patoke/re-plants-vs-zombies/blob/main/SexyAppFramework/SexyAppBase.cpp)：DrawDirtyStuff 的绘制、提交与计时边界。
- [WidgetManager.cpp](https://github.com/Patoke/re-plants-vs-zombies/blob/main/SexyAppFramework/widget/WidgetManager.cpp)：DrawScreen 包含控件遍历、图像锁/解锁。
- [WidgetContainer.cpp](https://github.com/Patoke/re-plants-vs-zombies/blob/main/SexyAppFramework/widget/WidgetContainer.cpp)：DrawAll 的控件可见性、裁剪和子控件遍历。
- [Graphics.cpp](https://github.com/Patoke/re-plants-vs-zombies/blob/main/SexyAppFramework/graphics/Graphics.cpp)：Graphics 状态、构造与析构。

S6 EXE 已核对的对应调用：DrawScreen 为 `538EB0`（控件管理器通过栈传入，ret 4）；MTRand 绘制允许标记为 `5A98B0`；`LawnApp+458` 是当前绘制标记；Redraw 在 App 虚表 `+170`。误把 MarkAllDirty 或表面重新初始化当作 DrawScreen 的早期实验已被运行证据否定，不应再用。
