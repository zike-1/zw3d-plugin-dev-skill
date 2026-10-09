# 已有二进制免编译安装EXE：开发分支验证

日期：2026-10-09。范围：`feat/lean-build-and-plugin-entry-v2`，候选技能0.2.5-dev；不是正式发行或中望3D GUI全流程验收。

## 实现与使用

```powershell
python -X utf8 tools/package_existing.py work/my-prebuilt-plugin --out dist --installer
```

输入仍为符合原v1契约的`plugin.json`及已有`payload/`。输出同版本的`.zwplug`和`-setup.exe`。
作者只需Windows及Python；不探测MinGW、不调用编译进程、不下载工具链、不重新编译或加载业务DLL。
可选`--sdk`做额外导入符号检查。安装时仍验证中望3D 2027目标和实际所需API。
省略`--installer`保持原只生成包行为；HubManager不直接导入裸包。

安装器模板1.0.0由原`framework/setup.cpp`一次构建，未修改框架源码；MinGW仅供维护者构建模板。
模板用Windows资源更新API填充包、描述、图标及冻结框架，使用独立检查器逐字比对嵌入文件。
非资源节字节保持相同；资源增长时允许Windows调整后续节的位置。模板和生成EXE未签名。
原`runtime/1.1.4`及所有历史运行时逐字保持不变，正式0.2.4 ZIP未覆盖。

## 已执行结果

| 验证 | 结果及范围 |
|---|---|
| 预编译打包与安装器回归 | 18项PASS；其中11项新安装器检查，包含DLL/EXE、自定义图标、空PATH和禁止子进程、可复现性、模板/框架损坏、签名模板拒绝、资源写入失败、发布回滚、代码修改检测及真实EXE拒绝错误目标 |
| 原包契约 | 26项PASS |
| 原构建环境、kit同步、界面标签、发布保护、项目模板 | 6+2+3+3+4项PASS |
| 技能组装 | 13项PASS；包含新增模板损坏保护及历史发行文件保护 |
| 安装器模板两次独立构建 | SHA256相同，MinGW-w64 GCC 16.1.0，x64 UCRT |
| 真实安装EXE隔离操作 | 29条断言PASS；用既有ArtHello DLL及ArtNotes EXE，空PATH且不提供SDK参数生成安装器。目标仅复制2027的两个宿主文件，不启动真实CAD会话 |
| 隔离共存、升级、卸载 | 共用一个页面并保留外来菜单；升级A后B字节及登记不变；卸载A后B实际运行`/probe`成功；保留设置及按插件清理通过 |
| 等待重启 | 测试自己创建的挂起宿主进程，无CAD初始化；运行中卸载暂存、退出后应用通过 |
| 独立候选ZIP | 完整性、两次组装哈希一致；仅解压候选技能，在仓库外、空PATH且无SDK参数成功生成并校验安装EXE，业务DLL字节保持不变 |
| 技能格式 | skill-creator的quick_validate通过 |

上述单元回归合计75项，另有29条隔离原生安装断言。原始本机证据保存在忽略的`verification/`，复现入口为`tests/prebuilt_installation.py --help`；需自行提供合法SDK及两个已编译示例包，不分发宿主文件。
GitHub Actions复现不依赖专有SDK的回归，并上传候选技能ZIP。

冻结模板SHA256：`c3eb026f3388164cac5dbb725c2f321647d02904cbd95b7ade9844bf362568ac`。
模板体积：1,452,544字节。候选ZIP约2.4 MB，含框架与模板；作者无需下载截图中的约707 MB编译工具链。

## 未执行或不属于本次变更

未在正式中望3D GUI中点开页面、点击业务按钮或验证模型操作。
未把旧WebPub/SplineTool的`!`模板命令、Form资源及自有Ribbon自动改造成Hub入口；仍需按真实插件适配。
未修改每包32入口限制、环境子集规则或原生多级菜单协议。
仍保留草稿PR，不合并main，不发布正式新版。
