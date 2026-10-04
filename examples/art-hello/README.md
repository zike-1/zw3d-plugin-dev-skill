# 优雅问候

这是一个不修改模型的最小示例。请先验证编译、安装和卸载，再实现业务功能。

DLL 名称为 `ArtHello.dll`，导出 `ArtHelloInit` 和 `ArtHelloExit`；SDK 命令为 `ArtHelloShow`，工具箱通过 `~ArtHelloShow` 调用。

源码不包含 SDK 安装路径。DLL 从自己的模块路径、EXE 从自己的程序路径确定目录，
不要用当前工作目录查找随包资源。

仅在专用测试进程中设置 `ZW_HUB_DEMO_LOG` 为绝对文件路径后调用命令：写入测试标记，并跳过提示窗口。普通使用不读写文件。

修改 ID、prefix、文件名、导出函数名和命令名时应同步修改。一个包只能声明自己的
命令；界面、安装、升级和卸载由共用工具箱处理。

使用工具包的`tools/build_plugin.py`并传入本示例目录；工具包位于源码仓库根目录或独立技能的`assets/kit/`。不要把SDK头文件或库复制到插件包。

1.1.0提供蓝色图标。执行`python examples/art-hello/make_icon_update.py --out work/hello-icon-update`创建1.1.1项目，只改变版本和图标颜色，随后用同一构建器打包。先装1.1.0与便签，再装1.1.1，验收问候图标变为橙色而便签及设置保持不变。生成器拒绝覆盖已有输出目录。
