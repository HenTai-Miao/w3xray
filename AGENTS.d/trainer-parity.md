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

## 剩余未看 (第 25 轮全清单审计后修正)

第 37 层对全部 134 个 war3 系模块做了声明行级覆盖审计, 抓出 5 个
曾被抽样扫尾漏掉的只读模块并补挖 (discovery_selection/properties/
fields/stats/unit_bindings_protocol) — 「矿脉穷尽」的依据从抽样扫
尾升级为全清单逐项声明行审计。补挖收获三条同构纪律: 原生调用行为
独立指认管理器 (IsUnitSelected, 我们无指令层不适用)、代码推导的槽
位布局不暗示其它模式 (我们 oversized-slot 修复教训的形式化)、布局
字节窗口逐成员证明后才推导 (我们 UNIT_FIELD_LAYOUT provenance 同
构)。全部 134 模块声明行已消费, 无剩余读路径空白。第 26 轮按「大模块必
须看内容」标准补看 ≥19KB 残留 (discovery_fields 58.7KB/stats 19KB),
再收两条架构级验证纪律: 「父组既有证明不得掩盖新出现的子冲突」
(证据层级失效传播) 与「重复消费者身份拒绝叠加为更确信 + 看不懂的
函数体保持未解析」(见证去重与不猜的字段层具体化)。至此 ≥19KB 模
块内容全看, 静态矿脉按自定标准穷尽。第 28 轮尾巴清零: CArchive m/s/o 全为
PyInstaller 运行时组件; archive_fields 的 .w3v/.w3z 存档读英雄物
品栏 (64MB 上限) 与 save_container 同构; war3_save_codes 与我们
savecodes 全面同构 (同正则/同载体/同「map-unverified candidates」
状态标注), 其 scan_memory_codes 揭示待需求项 — 加密图静态读不到
存码时, 运行时内存私有堆可扫 -load 明文候选 (保留边界暴露扫描间
隙), 对应我们提取阶梯第③层, 真有人问存码再建。第 27 轮对 ≥19KB 声明做最终清零核对
(facade_native/selection 纯门面, engine_transport 桥接传输含写链与
「排队消息≠回调, 要真实排空证明」纪律, equipment_effects 写事务,
三个 UI 模块纯 Tk 线程纪律 — save_extraction_ui 轮询队列与我们
gui_worker_host 同构, ability_fields 生成目录+重复键防呆,
operations 的 is_read_query「读写分类只认固定操作目录, 绝不信任调
用者标签」— 我们只读边界靠代码结构不靠运行时标签, 同构)。至此
≥19KB 内容清零核对完成, 静态矿脉最终穷尽。第 29 轮抓获 ≥19KB 最后两个漏网并清零:
speed_clock_backend (故障隔离「已知损坏路径退出时无关写入保持可用」
— 与策略链回退同构; 驻留映像只读验证「no new code ran」) 与
batch_edit (纯写路径数据模型)。≥19KB 内容级至此零遗留。第 30 轮补
看 gamecache_fields (20KB) — 「不猜」纪律在文件解析层的最完整文案
集: 每条错误消息都带「未做什么」句式 (未套用错误布局/未显示猜测
数值/未把候选当已识别/未把部分记录当全部结果), 且「读框架化嵌入
缓存块而非任意字符串匹配」— 我们 notes 有原因+建议但没有系统性
写「拒绝了什么猜测」, 解析类错误文案可参考此句式。hero_skill_
catalog/casc_catalog 为 SHA-256 内容寻址数据件, 归类正确。下一步在
真机: live --players --resources auto --export-profile。
