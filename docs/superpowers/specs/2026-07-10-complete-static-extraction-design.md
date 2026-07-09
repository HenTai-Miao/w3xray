# 设计：补全真实 WTG、CASC 与静态提取工作流

- 日期：2026-07-10
- 状态：已批准设计，待实施
- 范围：`w3xray` 的只读地图分析、资料包、桌面 GUI、CLI 和 Windows 打包

## 背景

当前版本已经能整理普通 MPQ 地图中的对象、脚本、WTS、资源、配置、预放置数据、
地图身份和存档/API 线索，但完成度审查发现以下声明没有达到真实用户能力：

- WTG ECA 按自造二进制布局读取，真实文件可能被静默错读。
- TriggerData 只支持自造 `Template/Args` 文本，不支持游戏实际的
  `TriggerData.txt` 函数签名和 `TriggerStrings.txt` 显示文本。
- GUI 只显示触发器头，没有事件、条件、动作和嵌套调用树。
- 原生 CASC 必须预先提供私有路径映射，普通官方安装目录不能直接读取。
- 外部 listfile 只参与导出，错误条目还会污染资料包的“存在文件”结论。
- `需求覆盖.tsv` 是固定声明，不反映当前地图的实际源数据和解析结果。
- 部分资料包写入缺少统一的目标路径、符号链接和竞态防护。
- 完全打不开的保护图只得到通用错误，无法区分损坏、格式不支持和疑似保护。

## 目标

- 按真实 Classic/Reforged WTG 布局解析 ECA，参数数量由 TriggerData schema 决定。
- 同时读取 TriggerData 和 TriggerStrings，生成接近 World Editor 的本地化句子。
- 在 GUI 提供可展开的触发器 ECA 树和参数详情。
- Windows 上使用 CascLib 直接读取普通 Warcraft III CASC 安装目录。
- 保留散文件目录和现有纯 Python path-map/BLTE 后端作为回退。
- 让外部 listfile 参与地图加载、GUI 分析、导出和资料包，并验证名称真实性。
- 按当前地图和数据源动态生成需求覆盖状态。
- 统一所有导出写入的路径安全和错误处理。
- 对打不开或部分可读的地图给出分级静态诊断。
- 保持现有 MPQ、战役、对象、脚本和资料包接口向后兼容。

## 非目标

- 不执行地图脚本、平台 API 或未知二进制载荷。
- 不做调试器注入、进程内存读取、运行时明文转储或保护绕过。
- 不承诺恢复源文件中不存在的对象名、动态拼接字符串或运行时计算值。
- 不把静态启发式诊断描述成确定的加密类型识别。
- 不自行实现加密 BLTE 的密钥获取；CascLib 能合法读取的客户端内容由其处理。

## 方案选择

### A. 全纯 Python

自行解析 `.build.info`、build config、Encoding、Root、idx/data 和所有 Root 变体。
跨平台，但实现和验证成本最高，最容易再次出现“合成 fixture 通过、真实安装失败”。

### B. 仅 CascLib

真实 CASC 兼容性最好，但 Windows DLL 成为唯一入口，现有 macOS/Linux 开发测试和
散文件工作流退化。

### C. 混合后端（选定）

Windows 优先使用成熟 CascLib；散文件目录继续使用 `DirectoryDataSource`；已有
path-map + 非加密 BLTE 后端保留为可测试回退。统一暴露 `GameDataSource` 协议，
上层 TriggerData、图标和资料包不感知后端。

选 C 的原因：真实安装兼容由成熟实现负责，现有跨平台测试和无 DLL 场景仍可运行，
同时不再把 sidecar 原型称为完整原生 CASC。

## 架构

### 1. 触发器 schema

新增独立 schema 层，职责仅是解析编辑器元数据：

- `TriggerData.txt`：解析事件、条件、动作、调用的版本标志、返回类型和参数类型序列。
- `TriggerStrings.txt`：保留重复键和原始顺序，解析函数显示名、提示和参数插槽文本。
- `TriggerSchema`：按函数类型和函数名返回确定的参数定义与显示模板。

加载顺序：

1. 用户选择的游戏数据源中的 `UI/TriggerData.txt` 和 `UI/TriggerStrings.txt`。
2. 可选的项目内兼容 schema 快照，仅在其来源、版本和生成方式可验证时使用。
3. 两者都没有时，只解析 WTG 分类、变量和触发器头；不猜参数数量。

任何函数没有 schema 时，记录“未知函数签名”，停止该函数的 ECA 读取并保留已确认数据，
不得把后续字节静默错位解释。

### 2. 真实 WTG ECA

`parse_wtg(data, schema)` 按 WTG 版本选择 Classic/Reforged 布局：

- 函数类型、名称、启用状态按文件读取。
- 参数个数和每个参数的语义类型来自 `TriggerSchema`。
- 参数读取覆盖常量、变量、数组下标、函数调用、begin/end function 标志。
- 子 ECA 读取版本相关的 group/branch 字段，再递归读取子动作。
- 所有计数、深度、字符串长度和剩余字节都有上限。
- 解析错误返回结构化诊断，包含触发器、函数、字节偏移和原因。

旧的 `has_unexpanded_functions` 拆成两个独立状态：

- `missing_schema_functions`：缺 TriggerData/TriggerStrings 或未知函数签名。
- `parse_failures`：WTG 截断、损坏或版本布局不匹配。

### 3. TriggerStrings 语义渲染

语义渲染使用 TriggerStrings 的真实显示结构，不把 TriggerData 的逗号签名当模板：

- 参数按 schema 位置绑定。
- 嵌套函数递归渲染。
- WTS `TRIGSTR_*` 经当前地图字符串表解析。
- 变量、数组和 rawcode 保留原值，并在已有对象索引中补名称。
- 缺少本地化文本时回退为 `函数名(参数...)`，原始列始终保留。

### 4. GUI ECA 工作台

新增“GUI触发器”主标签，采用与对象编辑器一致的双栏结构：

- 左侧 Treeview：分类、触发器、事件、条件、动作和嵌套调用。
- 右侧详情：本地化句子、函数名、启用状态、参数原值、参数类型和诊断。
- 搜索按触发器名、函数名、语义文本、变量和 rawcode 过滤。
- 固定列宽、惰性插入子节点，避免大图一次创建全部控件。
- 缺 schema、解析失败和正常空触发器使用不同状态文本。

已有“触发指令”继续表示聊天命令，不与 GUI 触发器混用。

### 5. 混合 CASC 数据源

新增 `CascLibDataSource`：

- 仅在 Windows 加载项目随包的 x64 `CascLib.dll`。
- DLL 来源、版本、许可证和 SHA256 写入第三方清单；打包脚本校验缺失或架构错误。
- 用 `CascOpenStorage` 打开用户选择的 Warcraft III 安装目录。
- 用 `CascOpenFile`/`CascReadFile` 按游戏内部路径读取 TriggerData、TriggerStrings 和图标。
- 所有原生句柄由上下文管理器关闭；错误码转换成带路径和操作的类型化错误。

`open_game_data_source()` 的顺序：

1. 普通散文件目录 -> `DirectoryDataSource`。
2. 原生 CASC + CascLib 可用 -> `CascLibDataSource`。
3. 原生 CASC + path map 可用 -> 当前纯 Python `CascDataSource`。
4. 都不可用 -> 返回不可读 probe，明确说明缺 DLL、架构或数据错误。

可选的 TriggerData/CASC 读取失败只关闭语义增强，不得拖垮整个资料包导出。

### 6. 外部 listfile 全链路

外部 listfile 在打开地图前解析，并通过加载上下文传给 `load_map`：

- 每个名称必须通过路径规范化和 `archive.has_file()` 验证。
- `MapData` 分开保存 `archive_files`、`external_confirmed_files` 和 rejected 诊断。
- GUI 选择/清除 listfile 后重新加载当前地图。
- GUI 文件、资源、配置、脚本扫描只消费确认存在的并集。
- 导出函数接收不可变名称序列，不再原地修改 `MapData.all_files`。
- 资料包记录 listfile 总数、确认数、重复数、危险路径数和不存在数。

### 7. 动态需求覆盖

`format_requirement_coverage(md, capabilities)` 根据当前地图计算状态：

- `已提取`：存在源数据且目标产物有有效行。
- `源数据缺失`：地图没有对应文件或对象。
- `部分提取`：有解析失败、缺 schema、未知块或低引用覆盖。
- `仅静态线索`：存档值、平台 ID、动态资源等只能报告调用位置。
- `不支持`：运行时解密等明确非目标。

矩阵增加 WTG ECA、TriggerData/TriggerStrings、CASC 数据源、外部 listfile 和保护诊断行，
不再固定写“已覆盖”。

### 8. 安全写入

新增统一输出路径模块：

- 拒绝空路径、父目录、驱动器路径、UNC/POSIX 绝对路径和 NUL。
- 解析目标父目录后验证仍位于输出根目录。
- 创建目录后再次验证真实路径。
- 支持的平台用 `O_NOFOLLOW` 打开最终文件；其他平台写前拒绝现有符号链接。
- 所有资料包资产、匿名块、脚本、ID 和“导出全部”复用同一写入入口。
- 添加符号链接、嵌套链接、绝对路径和检查/写入竞态回归测试。

### 9. 保护和损坏诊断

新增 `ArchiveOpenDiagnosis`，在 MPQ 初始化失败时只读检查：

- 文件不存在、权限或读取错误。
- 未找到有效 MPQ 头。
- hash/block 表越界、截断或计数异常。
- 有效块中匿名加密失败比例高。
- 未知格式或版本。

GUI、CLI 和资料包使用相同诊断文本。结论使用“疑似保护或损坏”，不声称具体保护器，
也不尝试执行、注入或读取进程内存。

### 10. CLI

保留 `main.py cli <地图>`，新增兼容参数：

- `--listfile <路径>`：参与加载和分析。
- `--game-data <目录>`：提供 Trigger schema 和游戏资源。
- `--pack <目录>`：生成资料包。
- 参数或地图解析失败返回非零退出码。

## 数据流

```text
GUI/CLI 选择地图、listfile、游戏数据
        |
        +--> open_game_data_source
        |      +--> DirectoryDataSource
        |      +--> CascLibDataSource
        |      +--> path-map CascDataSource
        |
        +--> load TriggerData + TriggerStrings --> TriggerSchema
        |
        +--> open MPQ --> 验证外部名称 --> load_map(schema, confirmed names)
        |                                      |
        |                                      +--> WTG ECA + diagnostics
        |                                      +--> objects/scripts/resources
        |
        +--> GUI ECA tree / CLI summary / knowledge pack
                                      |
                                      +--> dynamic coverage
                                      +--> unified safe output
```

## 错误处理

- 缺 Trigger schema：地图继续加载，ECA 明确标为缺 schema。
- 单个未知 ECA 函数：保留此前数据并记录函数和偏移，不继续猜布局。
- TriggerStrings 缺本地化键：回退函数名和原始参数。
- CascLib 缺失或加载失败：probe 显示原因，并尝试纯 Python 回退。
- 单个 CASC 文件不可读：图标/语义增强降级，不中断资料包主体。
- listfile 条目无效：记入诊断，不进入存在文件集合。
- 导出路径不安全：跳过并写入 manifest，不写出输出根目录。
- MPQ 无法打开：GUI/CLI 显示结构化诊断和非零退出状态。

## 测试与验收

### 必须自动化

- 真实格式的 Classic 和 Reforged WTG fixture，覆盖变量、数组、嵌套函数和子 ECA。
- 真实格式 TriggerData/TriggerStrings 片段，验证签名与本地化句子。
- 反例测试证明旧的“参数数量内嵌”合成 WTG 不再被当作真实格式。
- GUI ECA 树的节点层级、详情、搜索和缺 schema/解析失败状态。
- 外部 listfile 的确认、拒绝、重新加载和不污染 `MapData`。
- 动态需求覆盖的完整、缺失、部分和不支持状态。
- 所有输出入口的穿越、绝对路径和符号链接测试。
- 可选 CASC/TriggerData 失败后资料包仍可完成。
- CLI 参数、资料包生成和失败退出码。

### Windows 集成

- 构建产物包含正确架构 CascLib DLL 和许可证。
- 在普通 Warcraft III 重制版安装目录读取 TriggerData、TriggerStrings 和一个 BLP 图标。
- 用真实地图打开 GUI ECA 树并导出资料包。
- CascLib DLL 缺失、错误架构和损坏安装目录均显示明确降级原因。

### 完成门槛

- 全套现有测试通过。
- 新增真实格式测试通过，不能仅有手工拼接的实现同构 fixture。
- Windows 集成结果有命令、版本和读取路径证据。
- 文档声明严格匹配实测后端和限制。
- 不产生项目内缓存、下载、截图或临时 fixture 残留。

## 文档与兼容

- README 区分“资料包 ECA”“GUI ECA”“原生 CASC 后端”和“静态保护诊断”。
- `docs/KKWE借鉴清单.md` 的完成状态按真实验收重新标记。
- `progress.md` 和 `findings.md` 删除互相矛盾的旧结论。
- 旧 `write_knowledge_pack(md, out_dir)` 和 `load_map(path)` 调用继续可用。
- 旧的 path-map CASC fixture 和散文件工作流继续通过。

## 实施顺序

1. 用真实公开格式和 fixture 锁定 WTG/TriggerData/TriggerStrings 红灯。
2. 重写 schema 与 WTG ECA 核心，完成 TSV 和诊断。
3. 接入 GUI ECA 工作台。
4. 重构外部 listfile 加载上下文和动态覆盖矩阵。
5. 统一安全写入和保护图诊断。
6. 实现 CascLib 后端、打包和 Windows 集成测试。
7. 补 CLI、文档和全套回归。
