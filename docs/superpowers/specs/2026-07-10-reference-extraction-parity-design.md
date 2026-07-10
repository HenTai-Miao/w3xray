# 设计：参考软件静态提取能力完整对齐

- 日期：2026-07-10
- 状态：待书面复核
- 参考程序：`魔兽多功能存档盒子1.8.0.9`
- 目标项目：`w3xray`
- 逆向工具链：Ghidra 12.1.2 + Oracle JDK 26.0.1

## 背景与证据

参考 EXE 是受保护的 32 位原生 Windows 程序，不是 .NET、Electron、Python 或 Node
封装。静态字符串、导入调用和 Ghidra 反编译共同确认，其地图 ID 提取入口会：

1. 把用户选择的地图复制为 `提取ID.w3x`。
2. 通过内嵌 StormLib 调用打开 MPQ，并读取 `war3map.wts`。
3. 读取地图内 `Units\\*Func.txt` 与 `*Strings.txt` 文本对象数据。
4. 读取 `war3map.w3t`、`war3map.w3u`、`war3map.w3a`、`war3map.w3q`。
5. 合并文本与二进制对象，解析 `TRIGSTR_*`。
6. 生成按 rawcode 排序、去重的物品、单位、技能、科技四类报告。

参考程序不执行通用地图编辑，也没有证据表明其 ID 提取入口会执行 loader、调试目标
进程、读取运行内存或调用平台存档 API。参考 EXE 中与登录、注入、运行时存档有关的其他
模块不属于本设计。

`w3xray` 已经覆盖 MPQ、WTS、二进制对象、SLK、WTG/ECA、CASC、资源、地形、
只读存档证据和资料包等更大范围，但实测发现若干合并与发布错误会造成“文件读到了，
最终结果却丢对象、乱码或导不出”。本设计修复这些静态提取缺口，并补齐直接影响参考
程序开档成功率的 StormLib 兼容能力。

## 目标

- 对齐参考程序四类 ID 提取的输入、合并、WTS 解析、去重和排序语义。
- 所有 Warcraft 文本入口统一兼容 UTF-8、GBK 和当前 Windows ACP。
- 文本、二进制、SLK 和基础客户端数据按对象码合并，不再按整个分类互斥。
- 自定义对象继承基础对象缺失字段，同时保持基础对象索引不被自定义对象覆盖。
- 双脚本、WTG/WCT、战役子图、资料包和 CASC 回退源的静态结果可完整发布。
- 解析或写入失败必须形成结构化诊断，不能静默伪装成“源数据不存在”。
- 对直接影响已知文件读取的 MPQ 头、压缩链、名称和 locale 行为补齐兼容。
- 保持现有 GUI、CLI、`load_map()` 和资料包调用兼容。

## 非目标

- 不执行地图脚本、内嵌 loader、平台 API 或未知二进制载荷。
- 不注入进程，不读取或转储运行内存，不关闭反调试或反作弊机制。
- 不解密平台私有存档，不修改玩家存档。
- 不声称恢复运行时生成、源文件中不存在或必须持有外部密钥的数据。
- 不复刻参考程序的卡密、登录、平台检测或注入功能。

## 方案选择

### A. 只修四类对象输出

仅修 GBK、WTS、文本/二进制合并和报告格式。改动最小，但不能解决同一批审计中已复现
的战役子图导出失效、二进制脚本误发布、错误静默和部分 MPQ 文件打不开。

### B. 对齐对象链并闭环现有静态发布链（选定）

统一对象合并内核，同时修复脚本、ECA、战役子图、CASC 回退源、诊断和写入结果。
在纯 Python MPQ 层补齐直接影响具名文件读取的 StormLib 行为。该方案覆盖“参考软件能提，
本项目提不全”的已确认根因，同时维持只读边界。

### C. 直接把 StormLib 设为唯一地图后端

Windows 兼容性高，但会让 macOS/Linux、单元测试和纯 Python 分发退化，并新增原生 DLL
生命周期与打包风险。StormLib 仅作为行为基准和真实 fixture 生成器；本轮不把它设为
唯一运行时后端。

## 架构

### 1. 拆分高层加载职责

`w3xtool/api.py` 当前约 615 行纯代码，混合对象构建、脚本读取、地图加载和战役递归。
本轮修改会先按职责拆分，保持 `api.py` 为兼容门面：

- `object_pipeline.py`：对象候选、来源优先级、字段合并、继承、去重和索引。
- `object_text_sources.py`：具名/匿名 Func/Strings 发现、Warcraft 文本解码和 INI 解析。
- `script_sources.py`：JASS/Lua/WCT 可读脚本收集及分析文本组合。
- `campaign_sources.py`：战役子图的持久可重开来源与生命周期。
- `extraction_diagnostics.py`：组件级读取、解析和发布诊断。

每个模块保持单一职责和不超过 250 行纯代码。现有公开类型与函数从 `api.py` 继续导出，
避免 GUI、CLI 和测试调用断裂。

### 2. 文本对象来源发现

来源分为两类：

- 具名可信来源：已知 `Units\\*Func.txt`、`Units\\*Strings.txt` 和 archive/listfile 中
  名称匹配的文件。只要语法有效就解析，不使用“至少 8 个对象”的阈值。
- 匿名块启发式来源：继续检查块头和对象特征，并保留对象数、字段信号和容量上限，降低
  把普通 INI 当对象表的误报。

所有字节通过 `decode_warcraft_string()` 解码。每个来源生成不可变候选记录，包含 rawcode、
推断分类、原始字段、来源路径、来源类型和诊断；不在发现阶段直接修改 `MapData`。

同一 rawcode 在 Func 与 Strings 中出现时按字段合并。合并不依赖 MPQ 枚举顺序：文件名先
做大小写无关规范化并排序；Strings 对 `Name`、`Propernames`、`Tip`、`Ubertip`、
`Description` 等显示字段优先，Func 对非显示字段优先；同类文件中的重复字段按规范化文件名
顺序取最后一个非空值。所有被覆盖值仍保留来源记录供诊断和导出。

### 3. 统一对象合并

对象数据按以下顺序进入统一合并器：

1. 内置或客户端基础对象，作为继承底座。
2. 内嵌 SLK，提供完整默认字段和优化图数据。
3. Func 文本中的非显示字段和二进制 `war3map.w3*` / `war3campaign.w3*` 修改项；若两者
   同时显式修改同一非显示字段，二进制修改优先。
4. Strings/Func 文本中的显示字段，作为地图内本地化文本覆盖。

合并规则：

- 身份键是 `(分类, obj_id)`；同一分类同一 rawcode 最终只有一条记录。
- 不再用“文本覆盖整个分类”跳过二进制文件。
- 自定义对象以 `base_id` 找基础对象并继承缺失字段；自己的修改值覆盖继承值。
- SLK 可给二进制对象补缺失字段和引用，但不覆盖已有二进制修改。
- `Name`、`Propernames`、`Tip`、`Ubertip` 等字符串在写入候选时统一解析 WTS。
- `obj_index` 只按真实 `obj_id` 建索引；自定义对象不得以 `base_id` 别名覆盖基础对象。
- bucket 和索引都执行确定性去重；来源冲突进入诊断，不静默丢弃。
- 名称、图标、搜索文本和引用图在最终合并后统一重建，避免字段已补齐但派生值仍陈旧。

### 4. 兼容报告

四类盒子兼容报告只包含最终合并结果，并按 rawcode 的字节序稳定排序：

- 单位：`ID`、`名字`、`描述`；描述值以 `称谓：<Propernames>` 开头，空一行后接
  `Ubertip/Description`，与参考报告一致。
- 物品、技能、科技：`ID`、`名字`、`描述`。
- `Propernames` 支持逗号分隔多个称谓。兼容报告保留源数据中的 `|c...|r`、`|n` 等
  Warcraft 富文本标记，只规范化文件换行；结构化 TSV 继续提供清理后的可读值。
- unresolved `TRIGSTR_*` 原样保留并同时写诊断，不伪造空文本。
- 相同 rawcode 不重复输出。

结构化 TSV 采用同一排序与去重结果，避免 GUI、TSV 和兼容文本互相矛盾。

### 5. MPQ/StormLib 读取兼容

以真实 StormLib 生成的最小 fixture 锁定以下行为：

- MPQ user-data 头和扩展头偏移定位。
- 多算法压缩掩码按 StormLib 的逆压缩顺序逐层解码。
- LZMA 使用其 StormLib 特殊标记单独派发；ADPCM mono/stereo 按合法 mask 与现有 zlib、
  bzip2、PKWARE、Huffman、sparse 链组合。
- 文件名转 MPQ hash 前按 Warcraft/Windows 字节规则编码，不能先对 Unicode 字符逐码点哈希。
- hash 命中按 locale/platform 选择，优先精确 locale，再回退 neutral。
- 具名文件、外部 listfile 文件和导出路径使用同一规范化规则。

解压继续执行输出长度、扇区数量、递归层数和总容量上限。未知或不支持的压缩组合保留
原始 payload 和诊断，不进行无界猜测。

### 6. 脚本与 WTG/ECA 发布

- `md.scripts` 只放可读文本：`war3map.j`、`war3map.lua`、WTS 和解码后的 WCT 虚拟文本。
- 原始二进制 `war3map.wtg` / `war3map.wct` 不再作为文本导出或进入脚本调用扫描。
- 同时存在 JASS 与 Lua 时，两份都建立函数、调用、字符串、对象码和特征索引；不再只选第一份。
- JASS 专用全局索引明确只处理 JASS；Lua 由独立语法路径处理，结果在发布层合并。
- ECA TSV 和 GUI 语义渲染都传入 WTS 与对象名表。
- ECA 参数递归导出包含 `array_indexer`，并保留原始值和语义值。
- WCT 截断、未知版本或部分解析形成诊断；可确认的前缀内容仍可发布。

### 7. 战役子图生命周期

当前子图加载后会删除临时 MPQ，再把 `path` 改成逻辑名，导致地形、资源正文、身份哈希和
资料包稍后无法重开。本轮引入只读 `ArchiveSource`：

- 普通地图来源为文件路径。
- 战役子图来源为受控临时文件或有界内存字节，生命周期由顶层 `MapData` 所有。
- `MapData.path` 保留用户可读逻辑名，所有需重开 archive 的功能使用 `archive_source`。
- 顶层对象释放或显式关闭时清理临时文件；异常路径同样清理。
- 子图身份哈希基于真实子图字节，不误用父战役或逻辑名。
- GUI 在选中子图时导出该子图；顶层“导出全部战役”仍递归导出全部关卡。

同时补全 W3F 的战役地图列表段，优先使用声明顺序，listfile/扫描只作为恢复回退。

### 8. CASC 数据源一致性

`DirectoryDataSource`、path-map `CascDataSource` 和 Windows `CascLibDataSource` 统一实现
可分页 inventory 能力：

- GUI 和 CLI 根据能力协议启用浏览，不再硬编码仅 `casclib` 可用。
- 已选择的客户端数据可用于基础对象重建、TriggerData/Strings 和图标。
- 资料包可按引用导出客户端来源图标，并标明来源；不冒充地图内文件。
- 无完整 Root 枚举能力的来源只列出可确认路径，并在状态中明确“已知路径视图”。

### 9. 组件诊断与写入结果

`MapData` 保存结构化组件诊断：来源、阶段、严重度、异常类型、消息和可恢复状态。脚本、
WTS、SLK、W3I/W3F、WCT、WTG、世界数据、配置和预览失败不再统一吞掉。

资料包写入返回逐文件结果而非 `0/1` 计数：

- 成功项记录相对路径和字节数。
- 失败项记录目标、错误类型和消息。
- GUI 汇总成功/失败数量，失败时不显示“完整导出成功”。
- manifest 和需求覆盖矩阵依据实际解析与写入结果生成。

## 数据流

```text
Map/Campaign bytes
  -> MPQ header/hash/locale/decompression
  -> WTS
  -> object sources [base, SLK, binary w3*, Func/Strings]
  -> normalize + inherit + merge + deduplicate
  -> MapData objects/index/references
  -> GUI + sorted TSV + four legacy reports

  -> readable scripts [JASS, Lua, decoded WCT]
  -> per-language indexes + WTG/ECA semantics
  -> knowledge pack

Every stage -> component diagnostics -> GUI/CLI/manifest
```

## 错误处理

- 单个对象来源损坏：保留其他来源和已确认对象，记录文件、偏移或 block。
- WTS 缺键：保留 token 并记录 unresolved 数量。
- 来源分类冲突：按更强格式信号选择分类，诊断中保留冲突双方。
- MPQ 压缩不支持：不返回伪解压数据；保留原始 payload 和算法掩码。
- 战役单个子图损坏：顶层和其他子图继续加载，并列出失败关卡。
- 资料包单文件写失败：继续其他文件，最终明确返回部分成功。
- 客户端数据源不可枚举：已知路径读取继续可用，浏览状态明确降级。

## 测试与验收

### 对象链红灯测试

- GBK/ACP Func/Strings 中文不乱码。
- 文本字段中的 `TRIGSTR_*` 通过地图 WTS 还原。
- 同 rawcode 的 Func + Strings 字段合并。
- 少于 8 条的具名对象文件仍解析。
- 同一分类文本与二进制对象同时保留并按 ID 合并。
- SLK 给二进制对象补缺失字段和引用。
- 自定义对象继承基础对象且不覆盖基础 ID 索引。
- bucket、索引和四类报告均无重复 rawcode。
- 四类报告按 rawcode 排序；单位包含 `Propernames/称谓`。

### 容器与发布测试

- StormLib fixture 覆盖 user-data、组合压缩、LZMA、ADPCM 和 locale 回退。
- JASS + Lua 同时存在时，两者的命令、引用和函数都可见。
- WTG/WCT 原始二进制不进入可读脚本；解码 WCT 只出现一次。
- ECA 语义包含 WTS、对象名和数组下标。
- 战役子图加载后仍能生成哈希、地形、资源正文和独立资料包。
- 目录/path-map CASC 源可浏览已知路径并提供基础对象和图标。
- 任一组件失败在 GUI、CLI 和 manifest 中可见。
- 写入失败产生部分成功结果，不被成功计数掩盖。

### 完成门槛

- 每个修复都有先失败、后通过的回归测试证据。
- focused tests、全量 pytest、静态检查和 CLI 冒烟全部通过。
- 使用真实 `.w3x` 和 `.w3n` fixture 执行加载、四类报告和资料包端到端测试。
- Windows 打包工作流通过；真实 Windows 魔兽安装验收仍按 PASS/FAIL/SKIP 如实记录。
- 参考 EXE 的四类报告样式与本项目输出做确定性对照。
- 不提交下载、Ghidra 工程、反编译输出、缓存或临时地图。

## 兼容与迁移

- `load_map(path)`、`MapData.objects`、`MapData.obj_index` 和资料包公开入口保持可调用。
- 新的来源、字段 provenance、diagnostics 和 write results 以默认值扩展数据模型。
- 旧调用仍可传文件路径；内部逐步改为 `ArchiveSource`。
- 盒子兼容输出只改变排序、去重、称谓和缺失字段，文件名保持不变。
- README 中“文本/二进制/SLK 自动合并”的声明只有在新端到端测试通过后才保留。

## 实施顺序

1. 建立对象链和 StormLib 兼容红灯 fixture。
2. 拆分 `api.py`，实现统一对象候选与合并。
3. 补齐 MPQ 头、压缩组合、名称编码和 locale。
4. 修复脚本、WTG/ECA 和组件诊断。
5. 修复战役子图生命周期、W3F 列表和资料包重开。
6. 统一 CASC inventory、客户端基础数据和图标发布。
7. 统一写入结果、GUI/CLI 状态和动态覆盖矩阵。
8. 执行端到端、全量、Windows 打包与代码复审。
