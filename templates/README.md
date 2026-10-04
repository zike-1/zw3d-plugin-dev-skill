# 用少量代码建立一个插件

模板只负责业务入口。共用工具箱负责功能区、独立安装、更新和卸载。

在工具包根目录（源码仓库根目录，或独立技能的`assets/kit/`）执行：

```powershell
python templates/new_plugin.py --type dll --id org.zwtools.my-plugin --prefix MyPlugin --name "我的插件" --out work/my-plugin
python templates/new_plugin.py --type exe --id org.zwtools.my-tool --prefix MyTool --name "我的工具" --out work/my-tool
```

输出 `plugin.json`、`src/<Prefix>.cpp` 和本插件的说明。目标已存在时会拒绝覆盖。
同时提供`src/HubData.h`数据目录帮助函数和`payload/resources/tool.png`默认图标，清单已经声明图标与提示。作者可以替换PNG；发行时增加插件版本，不修改稳定ID。基础构建器递归编译`src`下CPP及资源脚本，复杂项目也可先外部构建，再提供标准`payload/`打包。
生成器直接使用发行包的清单校验器：ID 为小写反向域名，prefix 为 2–32 个
ASCII 字母或数字且以大写字母开头，`Hub` 前缀保留给共用工具箱。
DLL 模板只使用 SDK 命令注册和注销接口；EXE 模板只使用 Windows 系统接口。
两者默认只显示中文提示，不读取、修改或保存图纸。

DLL 的 `Init` 重复调用不会重复注册。只有注册成功的命令才由 `Exit` 注销，
遇到其他插件的同名命令时返回失败，不会替它注销。增加多个命令时，若某一步
注册失败，必须按相反顺序撤回本次已成功的注册。

专用测试入口明确隔离：DLL 由 `ZW_HUB_DEMO_LOG` 环境变量开启，EXE 由 `/probe=`
参数开启。它们只向明确提供的绝对日志路径写入标记，并跳过交互窗口；不要在
用户正常运行的中望 3D 中设置测试变量。

编译使用工具包的`tools/build_plugin.py`和本机官方2027 SDK，向脚本传入生成的插件项目目录。生成的业务项目不自带构建脚本；发行包不包含SDK。
