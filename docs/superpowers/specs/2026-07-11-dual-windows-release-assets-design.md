# 设计：Windows Release 同时提供便携 ZIP 与单文件 EXE

- 日期：2026-07-11
- 状态：方向已确认，待书面审阅
- 范围：PyInstaller 构建入口、Windows GitHub Actions 验收和下一版 GitHub Release

## 背景

当前 Windows 构建使用 PyInstaller `onedir`：入口 EXE 位于同名目录中，运行时依赖旁边的
`_internal/` 和 CascLib DLL。该形式启动快、便于诊断、杀软误报较少，但用户不能只下载一个
EXE。现有 `v0.1.0` Release 因此发布的是便携 ZIP。

用户已确认下一版 Release 同时提供：

1. 保留完整目录的便携 ZIP，作为稳定和可诊断的版本。
2. 新增真正的 PyInstaller `onefile` EXE，提供单文件下载入口。

## 方案比较

### A. 只改成 onefile

下载最简单，但会丢掉启动快、容易排查的 onedir 版本。单文件启动时需要先解压到临时目录，
也更容易触发杀软启发式检测。否决。

### B. 两份完全独立的 spec

实现直观，但隐藏导入、CustomTkinter 资源、CascLib DLL 和许可证配置会复制两份，后续很容易
只修其中一份。否决。

### C. 一份参数化 spec，同时构建两种格式（选定）

保留当前 spec 的公共 Analysis、资源和原生 DLL 配置，由项目构建入口显式选择 `onedir` 或
`onefile` 收尾结构。两种产物共享同一份依赖清单，同时独立构建和验收。

## 目标

- 默认 `uv run w3xray-dist` 行为保持不变，继续生成 onedir。
- `uv run w3xray-dist --onefile` 生成单文件 Windows EXE。
- 两种产物必须来自同一提交、同一 Python 依赖和同一固定 CascLib 源码。
- Windows workflow 分别实跑两种产物的地图、战役、资料包、重复加载和 GUI 标签验收。
- workflow 上传 onedir 目录、单文件 EXE 和各自的 `acceptance.json`。
- 下一版 Release 使用新标签发布两个用户资产：便携 ZIP 与直接 EXE。

## 非目标

- 不制作 MSI/Inno Setup 安装器。
- 不增加自动更新器。
- 不在本轮引入代码签名证书；Release 说明需提示未签名 EXE 可能触发 SmartScreen。
- 不删除或重写已经发布的 `v0.1.0`，下一版使用新标签保持产物与提交可追溯。

## 构建结构

### 构建入口

`w3xtool/dist_build.py` 增加显式构建格式：默认 onedir，`--onefile` 选择单文件。构建配置负责：

- 选择产物路径：
  - onedir：`dist/魔兽地图提取器/魔兽地图提取器.exe`
  - onefile：`dist/魔兽地图提取器.exe`
- 向 spec 传递唯一、受控的模式值。
- 对两种 Windows 模式都执行 CascLib DLL 架构与 SHA-256 校验。

未知模式仍由类型化参数错误拒绝，不允许 spec 静默回退。

### PyInstaller spec

公共 `Analysis`、hidden imports、CustomTkinter 资源、CascLib DLL 和许可证只维护一份：

- onedir 使用 `exclude_binaries=True` 和 `COLLECT`，保持现有行为。
- onefile 把 `a.binaries` 与 `a.datas` 交给 `EXE`，不创建 `COLLECT`。
- onefile 启动时由 PyInstaller 解压到临时运行目录；`casclib_api.default_dll_path()` 继续从
  打包根目录定位解出的 `CascLib.dll`。

模式只由项目构建入口设置，直接执行 spec 时默认 onedir，避免意外改变开发者现有命令。

## Windows 验收与产物

Windows workflow 依次执行：

1. 构建固定版本 x64 CascLib。
2. 运行完整测试套件。
3. 构建并验收 onedir。
4. 构建并验收 onefile。
5. 分别保存验收 JSON。
6. 上传 onedir 目录和直接 EXE。

验收除现有地图/战役/GUI 流程外，还要确认打包运行时能定位并加载 CascLib DLL。没有真实
Warcraft III 安装目录时，只验证 DLL 和必需导出符号可加载；真实 CASC 读取仍由现有
self-hosted workflow 负责。

## Release 规则

- 实施提交通过 Windows workflow 后创建下一补丁版本标签。
- Release 附件至少包含：
  - `w3xray-vX.Y.Z-windows-x64.zip`
  - `魔兽地图提取器-vX.Y.Z-windows-x64.exe`
  - 两种格式的验收报告。
- ZIP SHA-256 和 EXE SHA-256 写入 Release 说明。
- Release 说明明确：ZIP 启动更快、便于排查；单文件 EXE 首次启动较慢且可能被 SmartScreen
  提示。

## 测试与完成门槛

- 构建参数测试覆盖默认模式、`--onefile`、未知参数和两种预期产物路径。
- spec 测试确认两种模式共用 CascLib/CustomTkinter 数据源，且 onefile 不创建 `COLLECT`。
- 本地完整 pytest 通过。
- GitHub Windows workflow 中两种 EXE 均成功启动并完成 acceptance。
- GitHub Release API 确认 ZIP、直接 EXE 和验收报告均为 `uploaded`。
- Release 标签指向实际构建提交，工作区保持干净。

## 风险与处理

- **启动变慢**：onefile 的临时解压是预期行为，保留 onedir 作为快速版本。
- **杀软误报**：保持 UPX 关闭；Release 说明披露未签名状态并提供 SHA-256。
- **CascLib 找不到**：增加打包运行时 DLL 加载验收，失败即阻止发布。
- **两种配置漂移**：使用同一 spec 与公共 Analysis，不复制依赖清单。
- **版本与产物错配**：不覆盖 `v0.1.0`，新标签只在对应 workflow 成功后创建。
