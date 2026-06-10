# 设计：给 `build_base_names.py` 加文件夹源（间接支持 CASC/重制版）

- 日期：2026-06-10
- 状态：已批准设计，待实现
- 范围：仅开发期一次性脚本 `build_base_names.py`，不影响运行时与打包产物

## 背景与问题

`build_base_names.py` 是一次性生成脚本，从游戏安装目录的经典 MPQ
（`war3.mpq` / `War3x.mpq` / `War3Patch.mpq` / `War3xLocal.mpq`）里读取
`Units\*Strings.txt`、`Units\*Func.txt`、`Units\*Data.slk` 以及
`UI\WorldEditStrings.txt` 等，生成内置数据文件：

- `w3xtool/base_names.py`（原版码→中文名）
- `w3xtool/base_objects.py`（原版默认字段）
- `w3xtool/westrings.py`（编辑器字符串）

运行时**不读游戏文件**，只用这三个烤好的 `.py`，因此解析地图与游戏版本无关。

问题：自魔兽 1.30+（重制版）起，游戏本体数据从 MPQ 改为 **CASC** 存储，
`war3.mpq` 系列不复存在。脚本里的 `MPQArchive` 读不了 CASC，导致在重制版上
**无法刷新**这三份原版数据。

## 目标 / 非目标

目标：

- 让 `build_base_names.py` 能从**重制版**提取出的数据刷新原版名/字段。
- 改动可在当前 1.27（经典 MPQ）环境下**今天就验证**逻辑正确，不依赖重制版安装。
- 保持现有经典 MPQ 流程**向后兼容**。

非目标（YAGNI，明确不做）：

- 不在 Python 里实现原生 CASC 读取（不自写、不 vendor PyCASC）。
- 不做 CascLib 的 ctypes/DLL 绑定。
- 不自动探测重制版安装目录、不自动下载游戏数据。

## 方案选择

考察过三条路：

- **A. 纯 Python 读 CASC**：最贴合「无外部依赖」初衷，但 ~1000+ 行复杂代码；
  唯一的纯 Python 实现 PyCASC 自标 early-alpha/无文档，且不确定能处理 WC3 的
  `war3.w3mod`/TVFS 命名空间层；当前无重制版环境，**写完无法验证**，极易交付即坏。
- **B. ctypes 绑定 CascLib**：成熟可靠，但需携带原生库（仅构建脚本用，可接受），
  且仍**必须有重制版安装才能测**。
- **C. 源抽象 + 散文件目录模式（选定）**：不在仓库内读 CASC；把 CASC 格式解析
  甩给成熟的专用工具（CascView GUI / `wc3tools/casc-extract` CLI），脚本只新增
  一个「从普通文件夹读」的数据源。

选 C 的理由：当前无重制版可测，A/B 都只能「盲发等碰运气」；C 把不可靠的格式解析
交给久经考验的工具，仓库内只增加一个**今天就能在 1.27 上对拍验证**的文件夹读取器，
既达成「能从重制版刷新原版数据」的真实目的，又不引入测不了的代码。代价是用户需多跑
一步外部提取——对开发期一次性刷新脚本完全可接受。

## 架构

当前脚本对每个 `MPQArchive` 调用统一接口 `has_file(name) -> bool` /
`read_file(name) -> bytes`，并把「archive 列表」传给 `main()` 的两遍解析与
`build_base_objects()`。因此抽象点天然清晰：**把「数据源」做成可插拔，
只要实现 `has_file` / `read_file` 即可。**

### 组件 1：`DirSource`

把一个普通文件夹伪装成与 `MPQArchive` 同接口的数据源。

- 构造时**递归索引**整个文件夹，每个文件按「全小写 + 正斜杠」的相对路径登记，
  同时维护 basename→[相对路径...] 的辅助索引。
- 查询名（如 `Units\HumanUnitStrings.txt`）先规范化为「全小写 + 正斜杠」。
- `read_file` / `has_file` 共用同一套解析：`_resolve(name) -> 实际磁盘路径|None`。

`_resolve` 匹配顺序：

1. 规范化后**精确**相对路径命中。
2. 否则取索引中**以查询路径结尾**的项（吃掉 `war3.w3mod/` 等命名空间前缀）。
3. 否则按**文件名**命中。
4. 第 2/3 步若多候选 → 取**最短路径**并打 `warning`；零候选 → 返回 None
   （由调用方打「未找到 X」）。

设计意图：无论外部工具如何导出（带不带 `war3.w3mod` 前缀、大小写、斜杠方向），
都能把 MPQ 风格内部名对上磁盘文件。

### 组件 2：数据源构建 `build_sources(args)`

按 CLI 参数返回数据源列表：

- 默认 / `--game <路径>`：从该安装目录构造 `MPQArchive` 列表（与现状一致，
  低→高优先级 `war3 < War3x < War3Patch < War3xLocal`）。
- `--from-dir <文件夹>`：返回**单个** `DirSource`。

文件夹模式只用一个源——CASC 呈现的已是当前 build 合并/打补丁后的**最终态**，
不需要经典模式的「基础<资料片<补丁<本地化」多层覆盖语义。

### 组件 3：CLI

- `python build_base_names.py` —— 不变，从硬编码默认 `GAME` 读经典 MPQ。
- `python build_base_names.py --game <路径>` —— 覆盖 MPQ 安装目录。
- `python build_base_names.py --from-dir <文件夹>` —— 文件夹模式（重制版）。

`main()` / `build_base_objects()` 改为接收 `build_sources()` 的返回值，内部逻辑
（Strings 第一遍、Func 第二遍 `fill_only`、SLK 合并、WESTRINGS 提取）保持不变。

### 组件 4：可见性

文件夹模式下，对关键文件逐个打印「找到/未找到」，便于用户拿真实重制版跑时，
快速发现暴雪挪动/改名的文件（论坛提到部分数据可能在 `_Balance\` 下）。
无法预先解决未知的重制版布局，但保证**可调试**。

## 数据流

```
CLI args ──▶ build_sources()
                 ├─ 默认/--game ─▶ [MPQArchive, ...]
                 └─ --from-dir  ─▶ [DirSource]
                        │
                        ▼  （统一 has_file/read_file 接口）
   main(): 第一遍 *Strings.txt ─▶ names
           第二遍 *Func.txt(fill_only) ─▶ names
           UI\WorldEdit*Strings.txt ─▶ westrings
   build_base_objects(): Units\*Data.slk 合并 ─▶ base_objects
                        │
                        ▼
   写出 base_names.py / base_objects.py / westrings.py
```

## 错误处理

- 单个文件读取失败：沿用现有逐文件 `try/except` + 打印，不中断整体。
- `--from-dir` 指向不存在/空目录：构造 `DirSource` 时报清晰错误并退出。
- 关键文件缺失：打印「未找到 X」清单，但不崩溃（允许部分刷新 + 用户排查）。
- 匹配歧义（多候选）：取最短路径并 `warning`，不静默。

## 测试

- **单元测试（`tests/test_build_base_names.py`，今天即可在 1.27 跑，不需重制版）**：
  - 造合成文件夹，含 `Units/HumanUnitStrings.txt`（小写/正斜杠）、
    `war3.w3mod/units/itemfunc.txt`（带命名空间前缀）等。
  - 断言 `DirSource.has_file/read_file` 对 `Units\HumanUnitStrings.txt`
    （MPQ 风格反斜杠/混合大小写）能命中。
  - 断言前缀容忍（`war3.w3mod/` 被吃掉）、basename 兜底、缺失返回 None。
  - 可选：对合成 `*Strings.txt` + `*Func.txt` 跑解析，验证两遍合并（Func 只补缺）。
- **真实对拍（手动验证步骤，写进文档，不入自动测试以保持 hermetic）**：
  在 1.27 上把经典 MPQ 需要的文件导出到一个文件夹，分别跑默认模式与
  `--from-dir`，比较生成的 `base_names.py` 应一致，证明文件夹读取器逻辑正确。

## 文档

- 更新 `build_base_names.py` 顶部 docstring：说明 `--from-dir` 与重制版流程。
- README 增补一小节：用 CascView（GUI 点选）或 `wc3tools/casc-extract`
  （`war3.w3mod:units/*` 一行 glob）把重制版数据导到文件夹，再
  `python build_base_names.py --from-dir <文件夹>` 刷新。

## 影响面

- 仅改 `build_base_names.py` + 新增一个测试文件 + README/docstring。
- 不动 `w3xtool/` 运行时代码、不动打包、不改三份生成数据本身。
- 默认无参调用行为与现状完全一致。
