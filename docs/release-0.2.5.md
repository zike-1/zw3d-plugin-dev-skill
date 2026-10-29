# zw3d-plugin-dev v0.2.5 — 已有插件免编译生成安装器

发布日期：2026-10-29。适用范围：Windows x64、中望3D 2027 插件开发技能。

已有符合包契约的DLL/EXE、`plugin.json`和`payload/`时，可通过`tools/package_existing.py <项目目录> --out dist --installer`生成`.zwplug`和可双击安装的EXE。只需Python；不调用MinGW或重新编译业务程序。`--sdk`可选，用于额外检查宿主API。安装器模板和业务文件需要在本地，复用原冻结Framework 1.1.4。

## 下载

- `zw3d-plugin-dev-0.2.5.zip`：完整技能、模板、工具、框架和预编译安装器模板。
- `SHA256SUMS-0.2.5.txt`：正式技能包SHA256。发行工作流在构建同一次提交后生成。

## 验证范围

原开发分支执行了75项自动化回归和29条隔离安装断言，覆盖两个插件共存、升级、卸载、用户设置保留和等待重启；独立技能包在空PATH、不提供SDK打包参数时可生成并校验安装EXE。详见[2026-10-09验证记录](validation-prebuilt-installer-2026-10-09.md)。

正式中望3D GUI中的页面点击、业务模型操作及同事的复杂插件试用结果尚未取得，不将隔离验证视为真实GUI验收。原有`!`模板命令、Form和自有Ribbon需要单独适配；本版未改变每包32个Hub入口限制，未支持按环境隐藏或原生多级Ribbon自动迁移。HubManager仍不能直接导入裸`.zwplug`。

Framework 1.1.4和旧版本发行物保持原有版本；更新技能不会自动更新已安装插件。生成的安装器为未签名EXE。本项目不是中望官方产品，授权条款见`LICENSE`与`THIRD_PARTY_NOTICES.md`。
