# 中望3D插件开发技能

把一个功能写好，让它加入同一份工具箱。

这个项目包含AI技能、DLL与EXE模板、包检查器、单插件安装器和共用工具箱。每个插件都独立交付一份EXE：第一次安装建立“扩展工具”功能区，后续安装自动加入这里。管理器可以分别卸载插件，普通卸载保留个人设置和日志；正在运行的宿主把变更记为“等待重启”。

当前技能版本为**0.2.4**，共用框架版本为**1.1.4**，功能区名称为“扩展工具”。本轮在Windows x64与中望3D 2027 SDK环境下完成了构建修复、安装锁及隔离宿主的升级/界面检查；**尚未覆盖正式宿主GUI全流程验证**。0.2.3示例安装器继续保留其历史版本，不会因下载新版技能自动升级。`.zwplug`是本项目的包格式，不是中望官方格式。

## 下载与安装

**最新版技能：**从 [v0.2.4 发行页](https://github.com/zike-1/zw3d-plugin-dev-skill/releases/tag/v0.2.4) 下载 `zw3d-plugin-dev-0.2.4.zip`（Framework 1.1.4）；安装及打包方法见下文。

**旧版演示安装器：**以下文件仍来自 [v0.2.3 历史发行页](https://github.com/zike-1/zw3d-plugin-dev-skill/releases/tag/v0.2.3)，内嵌 Framework 1.1.3，界面沿用旧名称：

| 文件 | 用途 |
| --- | --- |
| `zw3d-plugin-dev-0.2.3-github.zip` | 给AI开发插件使用，包含完整技能、模板、工具及冻结框架 |
| `ZW3D2027-examples-0.2.3.zip` | 给中望3D用户体验，包含问候初装、便签和问候图标更新三个安装EXE |
| `SHA256SUMS-0.2.3.txt` | 两个下载包的SHA256校验值 |

**体验旧版示例插件（0.2.3）：**完整解压示例包，保存工作并退出2027，依次运行`01_ArtHello-1.1.0-setup.exe`和`02_ArtNotes-1.1.1-setup.exe`。重新打开2027，在“小插件”页使用问候、便签及管理插件。`03_ArtHello-1.1.1-update.exe`演示只更新问候图标，便签与其设置不受影响。详细步骤见包内`START-HERE.txt`。普通使用者不需要Python、SDK或编译器。

**想让AI制作新插件：**完整解压技能包，将其中的`zw3d-plugin-dev`目录放到Codex支持的技能位置。按[当前官方说明](https://learn.chatgpt.com/docs/build-skills)，Windows用户级位置是`%USERPROFILE%\.agents\skills\`，项目级位置是项目的`.agents/skills/`；已配置技能目录的环境可使用其现有位置。保留整个目录，不能只复制`SKILL.md`。技能未出现时重启Codex，并明确要求使用`$zw3d-plugin-dev`。其他支持`SKILL.md`的AI工具请使用其自身技能安装方式；本项目不承诺所有工具自动兼容。

需要编译插件时，另准备Windows x64、Python 3、MinGW-w64 x64工具链和合法安装的2027 SDK。

## 给AI使用

入口：[SKILL.md](skills/zw3d-plugin-dev/SKILL.md)。完整技能包组装后可独立安装，工具、模板、框架和冻结运行时位于技能的`assets/kit/`，无需依赖原打包电脑的共享盘。

示例请求：

> 使用 zw3d-plugin-dev 技能，为中望3D 2027开发一个插件。说明输入、输出、修改范围和成功条件；按技能交付完整源码、独立安装EXE和实际验证记录。

技能要求少而具体：功能归插件，入口归框架，数据归用户。SDK接口要从本机官方头文件确认。未执行的检查写“未验证”，不把编译通过当作功能验收。

## 开发一个新插件

开发机器需要Windows x64、Python 3、MinGW-w64 x64工具链，以及2027安装中的SDK。普通使用者只双击安装EXE，不需要Python、SDK或编译器。

```powershell
python -X utf8 templates/new_plugin.py --type dll --id org.example.art-demo --prefix ArtDemo --name "我的工具" --out work/art-demo
python -X utf8 tools/build_plugin.py work/art-demo --sdk "你的2027安装目录" --toolchain "你的MinGW根目录（包含bin）" --out dist
python -X utf8 tools/validate_package.py dist/org.example.art-demo-1.0.0.zwplug --sdk "你的2027安装目录"
```

示例身份必须换成团队自己的稳定ID与前缀。生成项目后实现业务功能，再构建。打包器默认复用`runtime/1.1.4/`的冻结框架；`--build-framework`只供框架维护者使用。不要各自重新编译同名框架版本再混装。

## 开发分支：复杂插件与预编译文件接入（尚未发布）

针对「一个插件包含很多内部命令是否必需拆包」以及「已有编译产物为什么还要安装 MinGW」的问题，
本开发分支新增了独立的预编译包创建器，详见 [复杂插件接入设计与真实宿主验收边界](docs/complex-plugin-integration-plan.md)。

已具备合法的 DLL/EXE 二进制及匹配的 `plugin.json`、`payload/` 时，可以在**仓库源码模式**运行：

```powershell
python tools/package_existing.py work/my-prebuilt-plugin --out dist
```

该流程不调用编译器、不重新构建已有 DLL，SDK 可通过可选 `--sdk` 参数提供，用于额外 API 检查。
**产出只有 `.zwplug`，不是可双击安装的 EXE；目前 HubManager 尚不能直接安装此包。**
因此完整的独立安装 EXE 仍需使用现有的 Windows 构建路径。

当前 32 条限制约束的是每个包在 Hub 清单中声明的功能区入口，而不是业务 DLL 内部的函数和子命令数量。
复杂插件可以仅暴露一个主入口，由自身界面呈现多个内部操作；如果原插件自带顶层选项卡，
其资源需要单独适配，不能认为载入 DLL 会自动迁移菜单。

以上属于尚未发行的开发分支工作，不属于正式 v0.2.4 技能 ZIP。不得据此声称环境分层显示、
任意旧 DLL 无修改导入或者完整原生 Ribbon 多级菜单已经完成。

## 项目结构

| 目录 | 职责 |
| --- | --- |
| skills/zw3d-plugin-dev | 简短的技能入口、按需读取的规范与验收方法 |
| templates | 创建DLL或EXE项目，直接复用同一份清单验证器 |
| examples | 一个不修改模型的DLL问候插件和一个EXE便签工具 |
| tools | 校验清单、PE架构与依赖，打包并生成独立安装EXE |
| framework | 通用加载、菜单、数据目录、安装事务和管理器 |
| runtime/1.1.4 | 所有作者复用的自编框架DLL与管理器，附SHA256 |
| tests | 合同、真实安装器、故障恢复与SDK宿主测试 |
| release | 组装技能和公开发行包的脚本；生成的ZIP从Release下载 |

## 怎样验证

包与模板检查可以在没有宿主运行的情况下执行：

```powershell
python -X utf8 tests/package_validation.py
python -X utf8 -m unittest discover -s templates/tests
```

`tests/test_installation.py`使用临时目录运行真实安装器，检查共存、卸载、保留数据、等待重启和恢复。`tests/test_host.py`会临时在本机2027安装测试插件，要求目标2027关闭，启动独立空白会话后恢复原文件；执行前检查脚本中的SDK和工具链位置。`tests/test_installed_host.py`用于已有安装的只读SDK状态检查；读取页面、父组、子控件标志不能证明实际绘制或鼠标点击。这些测试不会包含或公开SDK二进制。

`tests/test_standalone_skill.py`只使用技能ZIP解出的工具和模板，创建两个新插件并检查隔离共存与卸载，用于确认技能不依赖原打包电脑。

v0.2.4 的修复及发行范围见[发行说明](docs/release-0.2.4.md)；0.2.3 的历史结果见[原验收报告](docs/validation-report-0.2.3.md)。报告中的`verification/`路径为维护者保留的本机证据，不在公开仓库分发；复现请运行相应测试脚本。部分本机集成脚本带测试机SDK或编译器位置，运行前需按自己的环境核对。新版界面验收须同时检查页面、父组和子控件，并实际点开“扩展工具”页看到按钮、点击按钮及管理入口。仅子控件可见、SDK返回成功或直接执行命令不能作为界面通过依据。

## 边界

v1要求命令入口在首页、零件、装配和工程图环境可见；各环境须分别完成父组、子控件和实际点击验收。业务命令自行检查当前对象是否适用。暂不支持按环境子集隐藏、运行中卸载DLL、框架自身热更新、私有依赖DLL的动态搜索。每包最多32个命令，单个宿主合计最多128个EXE命令；不支持降级。

旧工具箱首次迁入协议1需关闭2027；0.1.1及更早EXE需重新生成。新安装器复用兼容的新框架，更新时不降级覆盖；框架运行中升级由独立程序暂存，关闭宿主后提交，再启动生效。详见[包契约](skills/zw3d-plugin-dev/references/package-contract.md)。

安装路径、源目录与数据目录分开。DLL可使用`framework/HubData.h`的接口获取自己的数据目录；EXE从`ZW_PLUGIN_DATA_DIR`获取框架传入的目录。普通卸载保留当前账户的数据；彻底清理只处理选中插件的数据。

本项目只分发自己编写的框架与示例，不分发中望SDK、宿主程序和既有供应商插件。原来八个工具的合并试用包仍是独立工程，本项目不会声称它们已全部符合新契约。

## 授权与反馈

这是公开源码、非商业授权的项目。允许非商业使用、修改和分享，须保留授权说明并注明作者`zike-1`及[项目来源](https://github.com/zike-1/zw3d-plugin-dev-skill)；商用需要作者单独书面同意。复制或改编的模板、示例及随包框架同样受此约束，自己独立编写的业务代码不因使用技能而自动改变授权。完整条款见[LICENSE](LICENSE)，运行库声明见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

问题反馈及商业授权申请可提交到[Issues](https://github.com/zike-1/zw3d-plugin-dev-skill/issues)。反馈请注明中望版本、插件版本、复现步骤和提示文字。更新情况见[CHANGELOG.md](CHANGELOG.md)。本项目由独立作者维护，不代表中望官方发行。
