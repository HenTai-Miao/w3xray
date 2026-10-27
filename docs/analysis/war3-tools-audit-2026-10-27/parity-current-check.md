> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# 历史 trainer 对照文档的当前源码核对

当前commit：ac18ec8d6e02dc36103d6c43cc0de61a0f83ab4e

已落地表19行全部核对；这是当前GameXRay侧状态复查，不是复用旧程序134模块全部看完的断言。本次不运行游戏和测试。

| 原文行 | 原设计 | 当前核对 | 当前源码 |
|---|---|---|---|
| 29 | 版本偏移矩阵+运行时校验 | 版本表、exact/RVA/template/pending分档与verify_profile仍存在；仅1.27.0.52240有已收录句柄链。 | gametool/live_handle_chain.py:126、gametool/live_handle_chain.py:297 |
| 30 | PE 指纹三要素 | 磁盘PE machine/timestamp/image_size三要素参与比对；不是整文件内容哈希同一性证明。 | gametool/live_inventory.py:432、gametool/live_handle_chain.py:297 |
| 31 | schema 版本化+分域 checks | schema_version=1与checks.domain存在；无v2多域Reforged实现。 | gametool/live_handle_chain.py:208、gametool/live_handle_chain.py:193、gametool/live_handle_chain.py:441 |
| 32 | ScanBudget 有界发现 | ScanBudget支持截止/取消/timed_out；live调用derive_offsets显式budget=None，不存在默认有时限发现。 | gametool/live_handle_chain.py:1361、gametool/live_inventory.py:1205 |
| 33 | 发现阶段化 | 当前DERIVE_STAGES恰为5键，且是Classic结构发现；文档16阶段不成立。 | gametool/live_handle_chain.py:1397、gametool/live_handle_chain.py:1408 |
| 34 | 字段证据行 (值+出处地址并列) | UnitInventory、SlotItem、OwnedUnit含地址；live输出单位、物品、owner、坐标及地址证据。 | gametool/live_handle_chain.py:707、gametool/live_handle_chain.py:698、gametool/live_handle_chain.py:764、gametool/live_inventory.py:1205 |
| 35 | 档案 JSON 固化+导入 | 导入/导出CLI参数与序列化代码均存在；失败降级说明；导出要求已得到可用句柄布局。 | gametool/live_inventory.py:415、gametool/live_handle_chain.py:389、gametool/live_inventory.py:1205 |
| 36 | 导入形状校验 | 四段版本、checks.rva及fingerprint三字段strict_int、未知dataclass键错误仍有；read_text无2MiB限制；game_struct_rva/unit_list_rva直接get，handle_chain成员未全面严格int验证。 | gametool/live_inventory.py:415、gametool/live_handle_chain.py:441、gametool/live_handle_chain.py:430 |
| 37 | 多实例不猜 | live与hero_chain main均保留--pid；多PID时不给隐式目标。 | gametool/live_inventory.py:1205、gametool/hero_chain.py:332 |
| 38 | PID 追溯 | report.pid与journal.pid均存在；PID是读数归因字段。 | gametool/live_inventory.py:1205、gametool/live_inventory.py:1099 |
| 39 | 进程身份复核 | verify_opened_process按打开句柄映像路径复核；handle/chain/icons/最终返回路径调用。未把此覆盖自动延伸给独立dump路径。 | gametool/live_inventory.py:211、gametool/live_inventory.py:1205 |
| 40 | 推导歧义可见 | 严格阶段收集所有候选并在source标记多解，按地址序首个；宽松阶段找到首个即返回。不能写成所有发现模式一律拒首匹配。 | gametool/live_handle_chain.py:1408 |
| 41 | 诊断日志三件套 | 异常stage/traceback写errors-v1.log、notes指路；journal失败可再分流errors日志，最终磁盘失败则fail-open。 | gametool/live_inventory.py:162、gametool/live_inventory.py:1099 |
| 42 | 失败可见化 | detect_version保留modules_seen；句柄策略未找到Game.dll时列出模块名提示。 | gametool/live_inventory.py:464、gametool/live_inventory.py:1205 |
| 43 | 证据地址固化 | 档案source及采样RVA/bytes存在；当前没有同构的独立references.json证据库。AGENTS里的历史地址不是本次重新采集。 | gametool/live_handle_chain.py:126、gametool/live_handle_chain.py:244、gametool/live_handle_chain.py:389 |
| 44 | 不可读精确判定 | snapshot按got.value!=requested累计_partial，不读取GetLastError以区别299；仅零可读+部分读取时给特定诊断。 | gametool/live_inventory.py:283、gametool/live_inventory.py:412、gametool/live_inventory.py:1205 |
| 45 | 方向性权限预检 | 五个RID名称与方向性self<game提示存在，无法读取则fail-open；不是自动提权。 | gametool/live_inventory.py:153、gametool/live_inventory.py:227、gametool/live_inventory.py:1205 |
| 46 | 三源 ID 目录 | base_names中文/英文/细分类表与base_catalog查询存在；根目录build_base_catalog.py记录固定源与合并逻辑。目录条目不等于当前地图可获得。 | gametool/base_names.py:4、gametool/base_names.py:3612、gametool/base_names.py:5991、gametool/base_catalog.py:12 |
| 47 | 快照模型 | 多区域顺序ReadProcessMemory到本地bytes后解析，改善复查一致输入；没有冻结游戏或引擎原子快照协议，不能声称天然免疫撕裂。 | gametool/live_inventory.py:283、gametool/live_handle_chain.py:573 |

## 原已入档待条件

- 共享映像DuplicateHandle/NtQuerySection/MapViewOfFile读路径：当前live读取路径是VirtualQueryEx/ReadProcessMemory；旧文档明确待重制样本，未找到公开入口。 进入条件：遇到真实关键页不可读且可证明只读时再设计/测试。
- RTTI/指令层定位与x64 ABI发现：现有derive_offsets使用Classic模板结构搜索，无完整指令解码/RTTI发现入口。 进入条件：引入可信静态指令/数据解析与真实版本证据。
- Reforged16阶段与schema-v2：resolve_profile重制路径为空RVA/handle链且tier=reforged-pending；当前schema只接受v1。 进入条件：真机样本、x64布局、选择/归属/字段校验与纯数据schema。
- 重制装备目录数据：现有base catalog来源与结构可借鉴；不能从旧文档495条历史数字推当前含该目录或当前地图可得。 进入条件：具体目录资产SHA256/许可/字段来源与地图适用性核实。

## 原有据不做与本次分类

- 写内存/装备编辑/批量编辑/单位玩家属性修改：outside_read_only_boundary；纯数据模型、字段目录、证据UI可另行评估。
- 双读一致性：adaptation_required；不能以现有快照名义判成永远无用；需根据具体读取语义验证。
- 指令级指针溯源：adaptation_required；先有静态指令解析与明确可支持ABI。
- TLS槽发现：adaptation_required；当前路径不依赖TLS；如新版本只读发现需要则独立适配。
- 桥接DLL或提取物执行：outside_read_only_boundary；只读分析其格式、接口和协议说明。
- 旧134模块/41轮/全部看完等覆盖断言：undetermined；仅作历史方法记录；不作为本次六程序覆盖证据。
