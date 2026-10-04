# 第三方组件声明

本项目自己的材料适用根目录[LICENSE](LICENSE)。下列组件适用其原有授权；本项目的非商业条款不改变第三方组件自身的授权。

## 编译进Windows发行物的运行库

冻结框架、示例及安装器使用WinLibs提供的GCC 16.1.0、MinGW-w64 14.0.0 UCRT / POSIX工具链构建。构建参数包含`-static -static-libgcc -static-libstdc++`。本仓库不分发编译器、调试器或其完整安装目录。

| 组件 | 授权与随附文本 | 上游 |
| --- | --- | --- |
| GCC运行库，包括libgcc及libstdc++ | GPLv3及GCC Runtime Library Exception 3.1；见`licenses/GPL-3.0.txt`、`licenses/GCC-RUNTIME-EXCEPTION-3.1.txt` | [GCC](https://gcc.gnu.org/) |
| MinGW-w64头文件及CRT | 不同文件使用公有领域、ZPL、BSD等声明；见`licenses/mingw-w64-COPYING.txt`、`licenses/mingw-w64-crt-COPYING.txt` | [MinGW-w64](https://github.com/mingw-w64/mingw-w64) |
| winpthreads | MIT及Lockless Inc. BSD声明；见`licenses/winpthreads-COPYING.txt`及本机头文件版权声明摘录`licenses/winpthreads-header-notices.txt` | [winpthreads](https://github.com/mingw-w64/mingw-w64/tree/master/mingw-w64-libraries/winpthreads) |

许可证来源及校验见[licenses/sources.json](licenses/sources.json)。未修改这些运行库；冻结发行物保留其实际程序内容。以后更换编译器、链接方式或新增依赖时，应重新核对所分发组件的声明。

## 开发与运行所需、未分发的组件

- 中望3D 2027及官方SDK由用户自行合法安装，遵守供应商授权；本仓库及发行包不包含官方头文件、SDK库、宿主程序或其他供应商插件。`tests/native/mock_sdk/`是本项目的简化测试声明，不代替官方SDK或承诺相同ABI。
- Python 3、MinGW编译器和Git是开发工具，不随本项目发行；Windows系统库和UCRT使用目标系统提供的组件。
- 插件按钮PNG为项目示例资源。原先其他作者的八个插件及其安装包未加入此仓库。
