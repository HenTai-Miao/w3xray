# trainer-parity: War3ReforgedTrainer 读路径设计对照矩阵

二十一轮换层下钻 (只读静态分析: marshal 结构化元数据 + CArchive 资产,
不做 co_code 字节码层) 的全景收口。每行: trainer 设计 → 我们对应物 → 状态。

## 已落地 (代码化, 提交在 20261005 分支)

| trainer 设计 | 出处 | 我们对应物 |
|---|---|---|
| 版本偏移矩阵+运行时校验 | profiles/*.json | HANDLE_CHAIN_OFFSETS + verify_profile (checks 字节) |
| PE 指纹三要素 | game_version/integrity | read_pe_fingerprint + fingerprint 比对闸 |
| schema 版本化+分域 checks | game_profile schema v5 | schema_version + domain 字段 (v1) |
| ScanBudget 有界发现 | discovery 族 | ScanBudget (超限=未完成可重试, 非失败) |
| 发现阶段化 | discovery_dependencies | DERIVE_STAGES 16 阶段 |
| 字段证据行 (值+出处地址并列) | facade_fields | addr 字段 (unit/owned/item) |
| 档案 JSON 固化+导入 | game_profile import | --export-profile / --profile-json |
| 导入形状校验 | game_profile _validate_shape | 2MiB 上限/四段版本/严格 int/未知键友好错误 |
| 多实例不猜 | find_war3 | --pid + 列 PID 拒绝猜 (live 与 hero_chain 同修) |
| PID 追溯 | EngineExecutionError | report["pid"] + journal-v1 行 |
| 进程身份复核 | GameSession.verify_opened_process | verify_opened_process (防 PID 复用) |
| 推导歧义可见 | discovery_validation 三态 | source 标 [多解歧义: N] / 宽松校验 |
| 诊断日志三件套 | error_messages format_error | errors-v1.log 带栈 + notes 指路 |
| 失败可见化 | GameModuleNotFoundError | Game.dll 未命中列出 modules_seen |
| 证据地址固化 | references.json | 证据地址入 AGENTS.md/档案 source |
| 不可读精确判定 | adapter SnapshotEx | _snapshot_partial (299 计数) |
| 方向性权限预检 | integrity require_matching | _integrity_rid + notes (我们 5 档 > 其 3 档) |
| 三源 ID 目录 | id_catalog | base_names.py + build_base_catalog 合并 (独立同构) |
| 快照模型 | PersistentNativeUnitSnapshot | snapshot() 全量快照 (天然免疫撕裂读数) |

## 已入档待条件 (AGENTS.d/live.md)

- 共享映像观察 (discovery_image: DuplicateHandle+NtQuerySection+MapViewOfFile 读受保护页, 边界内纯只读) — 待重制版真机出现读不到的关键页
- RTTI 定位纪律 (discovery_locators: 签名掩码策略/相对身份指纹/拒绝首匹配回退/交叉调用方/**固定 MSVC x64 ABI 而非游戏版本布局**) — 待反汇编基建
- 16 阶段重制版流水线 + v2 schema 骨架 — 待真机样本
- 重制版装备目录数据源 (new_equipment_catalog: 495 条+SHA-256, 官方目录≠地图可用) — 待重制版档案

## 独立同构确认 (两边独立收敛到同一设计)

- 三源 ID 目录合并 / resolve 快路径 (exact 零 I/O) / 方向性预检语义 /
  journal 请求域 / 资源锚点重验证 (表头未变也抽查) / 组件探测不声称选中语义 /
  官方目录≠地图可用 (声明级) / 每问必现取

## 有据不做 (边界/规模/架构)

- 写路径全家 (protocol/layout/loadout/batch_edit/adapter 12 布局适配器/操作依赖审计) — 只读边界
- 双读一致性校验 (classic_selection) — 快照模型天然免疫, 补了是死代码
- 指令级指针溯源 (discovery_abi GPR 写失效纪律) — 无指令解码层
- TLS 槽发现 (discovery_native) — 不走 TLS
- 桥接 DLL 执行 — 永不执行提取物
- 按命名归类的教训: id_catalog 曾被误归写路径 (36.5KB 未看内容) —
  归类条目至少看过声明行, 大模块必须看内容

## 剩余未看 (<8KB 桥接门面/写路径 UI 小件)

按依赖关系与命名归类为写路径/门面件; 边际收益低于换层成本。
静态矿脉已穷尽, 下一步在真机: live --players --resources auto --export-profile。
