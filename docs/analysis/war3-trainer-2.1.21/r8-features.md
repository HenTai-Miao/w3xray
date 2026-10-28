# R8 (1) static identity, current-source parity and adopted field semantics

Current-source baseline: `cfe9f68a023ae5f5e274101cb32f70f536bfb64d`. The only product edits owned here are `gametool/fields.py` and `tests/test_fields.py`.

New and old named EXEs are byte-for-byte identical, 18,821,684 bytes, SHA256 `20098c26644bb20f2a6a846e2ca94aedbe013d5260c3c46d1d5aaa4c0ef1fd2c`. Both inputs stayed byte/metadata stable. Independently decoded all 1,143 CArchive and 615 PYZ members match every previous name/type/offset/size/content hash. All seven first-party marshal hashes bind the prior complete disassembly; no target code was executed or imported.

## Coverage closure

Counts are evidence records, not independent product features. The historic R8 index has exactly 37 feature families + 50 callbacks; all 87 have one current review. UI declarations, repeated field constructors, metadata rows and CRT/runtime modules are kept as supporting indexes.

| Index | Records |
| --- | --- |
| functional_families | 37 |
| hotkey_callbacks | 50 |
| historic_index_rows | 87 |
| firstparty_modules | 7 |
| nested_code_objects | 1112 |
| decoded_instructions | 95769 |
| ui_declarations | 285 |
| cli_arguments | 53 |
| unit_field_constructor_sites | 53 |
| ability_metadata_rows | 753 |
| item_metadata_rows | 20 |
| id_records | 1950 |
| native_function_ranges | 136 |
| carchive_members | 1143 |
| pyz_members | 615 |

## Complete feature matrix

| ID / feature | Sample execution boundary | Current state / review |
| --- | --- | --- |
| `selection` 选中单位及多选快照 | active-game-thread-read | implemented-classic;needs-proved-reforged-layout — 完整多选、逐实例身份/坐标/背包与出处已实现。R8实际入口先常驻helper；x64复刻须有独立被动布局和真机，不能复用样本偏移。 |
| `selection_probe_alias` Native/JASS定位入口的实际行为 | active-game-thread-read | existing-equivalent;no-distinct-strategy — R8三个probe别名落到同一persistent snapshot。当前Classic推导真实独立；不能按旧函数名额外计三项能力。 |
| `bridge` 读取前置桥接边界 | hook-and-game-thread-execution | excluded-active-execution — LoadLibraryW/GetProcAddress/SetWindowsHookExW、消息和文件协议驱动游戏线程；不迁入只读GameXRay。 |
| `snapshot_fields` 单位详细字段 | active-game-thread-read | schema-implemented;needs-real-layout — 当前typed标量/指针链、raw bytes/address/state已存在；额外HP/MP/三围/攻击/护甲/技能点值需要当前build被动字段证据。 |
| `inventory` 背包与物品身份 | active-game-thread-read | implemented-classic;needs-reforged-layout — 当前Classic六槽身份、code、地址与逐实例交接已实现；R8数量等额外实时字段不得由静态目录推定。 |
| `abilities` 技能实例与字段读取 | active-game-thread-read | reference-implemented;runtime-layout-required — 字段元数据/地图技能证据已存在；wrapper/data/vtable/cache/运行时getter需独立x64布局，不能执行样本helper。 |
| `ability_catalog` 753条技能字段元数据 | offline-static-data | implemented-static-reference — 753条目录逐条核对。727条真实common.j常量与本项目全部一致；另26个METADATA占位名不是缺失native。Crs1只有已知常量、类型/适用性未知保持未知。 |
| `item_fields` 20条物品字段 | offline-catalog-plus-active-getters | static-reference-and-semantic-label-fix;runtime-layout-required — 20条字段逐项核对；iclb/ifil错标签触发本轮85项手工标签审计并修正17项。ihpc/ical无独立静态元数据；不补造runtime值。 |
| `resources` 玩家资源读取 | active-game-thread-read | implemented-classic-calibrated;reforged-layout-required — 当前金币/木材/人口校准与字段证据已有。R8固定28槽列表经helper，不能据该上限推广所有build或照搬合理值阈值。 |
| `passive_reader` 外部内存读取底层 | passive-rpm-with-optional-access-adjustment | existing-support — 底层RPM/区域/部分读诊断同构；它不是额外独立产品能力，也不使上层helper查询变为纯被动。 |
| `discovery` 保留的发现与定位代码 | retained-static-discovery-code | existing-classic;reforged-proof-required — R8保留大量native-name/rel32/组件扫描；已证明的活动入口另走helper。当前Classic推导已有，不能声称未证实x64活动路径可用。 |
| `profile` native表身份与硬编码布局 | hardcoded-runtime-native-layout | current-profile-system-stronger — R8硬编码NATIVE_INDEX/profile_id和历史地址无完整PE build矩阵。当前严格schema/来源/档案导入导出已有；只借目录结构，不借地址。 |
| `limits` 样本中的完整性边界 | limits-and-batch-protocol | current-completeness-contract-existing — R8选择上限64/批量selected12、能力4096保护、每批16操作均明确区分。GameXRay完整编码边界与显式whole-record limit已有，不移植静默上限。 |
| `window_identity` 进程与窗口选择 | process-and-window-selection | current-identity-stronger — R8省PID取首窗口；当前多实例拒猜、进程出生时间/路径复核更强。 |
| `write_unit` 单位与英雄修改 | game-memory-or-native-mutation | excluded-game-mutation — 单位/英雄写入及读回不采用；可展示静态字段与已证实的被动读数。 |
| `write_items` 物品与背包修改 | game-mutation | excluded-game-mutation — 生成/替换/复制/丢弃/清空/数量及神器均修改游戏；不是离线物品查询缺口。 |
| `write_abilities` 技能修改及组合 | game-mutation | excluded-game-mutation — 添加/删除/等级/重置/光环/被动及字段setter不采用。 |
| `write_item_fields` 物品字段编辑 | game-mutation | excluded-game-mutation — 物品Boolean/Integer/Real setter和读回属于修改事务。 |
| `write_resources` 资源与玩家修改 | game-mutation | excluded-game-mutation — 资源/人口/科技/经验倍率/联盟/和平模式写入不采用。 |
| `write_world` 单位/地图/游戏操作 | game-mutation | excluded-game-mutation — 开图/暂停/无敌/碰撞/大小/冷却/击杀/控制/创建复制均修改世界状态。 |
| `effects` 直接效果、buff与全屏技能 | game-thread-cast-and-mutation | excluded-game-mutation — buff/debuff/全屏技能与临时对象清理不采用；静态ack不是实机效果证明。 |
| `mouse_camera` 鼠标世界坐标 | active-game-thread-read-and-move | needs-real-passive-camera-input — 当前静态near/minimap坐标完整。R8鼠标世界点经helper相机路径；纯投影公式不足以证明可信相机/视口/地形来源。 |
| `cheats` 游戏聊天作弊输入 | posted-chat-input | excluded-game-input — PostMessageW聊天作弊及快速建造/胜利等不是只读能力。 |
| `locks` 周期锁定 | periodic-game-mutation | excluded-game-mutation — 周期资源/字段/我方锁血写入不采用；取消/关闭纪律在现worker机制已有。 |
| `hotkeys` 50项全局快捷键 | os-hotkey-dispatch-mixed-actions | existing-local-shortcuts;optional-global-read-probe — 50回调完整核对：1个选中读取仍经主动helper，49个修改/输入。当前离线hotkeys检查器不等于全局按键注册；可选全局只读probe是体验差额。 |
| `gui` 完整Tk界面 | gui-presentation-and-action-dispatch | existing-workspaces — 对象/字段/版本离线参考、live证据、子窗口生命周期等已有；训练器修改面板不迁移。 |
| `id_catalog` 1950条离线ID目录 | offline-static-data | existing-offline-catalog-and-local-import — 1,950条目录逐条做category/code当前对照，来源独立；现本地ID文本导入已经实现，不能重复报新功能。 |
| `localization` 中英文切换 | local-ui-language | optional-presentation-gap — 当前中英对象名/字段别名已有，整体UI语言切换未有。可用独立词条实现，目标词库许可未知不捆绑。 |
| `hover_dictionary` 内置悬停翻译 | local-widget-hover-only | optional-presentation-gap — 3395词条基于本软件Tk控件文本查词，不是游戏OCR。现固定工具提示已有，完整术语hover可选且须独立词源。 |
| `ocr_disabled` 旧OCR实现已禁用入口 | explicitly-disabled-entry | not-an-active-sample-feature — capture_physical_screen_image直接拒绝；保留OCR函数不能计成可用定位流程。 |
| `transport_protocol` 本地协议/事务 | hook-file-message-protocol | excluded-active-transport;not-product-feature — 协议69/互斥/事务/完成确认是helper执行支撑，不单列玩家产品能力。 |
| `async_lifecycle` 后台操作与生命周期 | local-worker-lifecycle | existing-equivalent — 串行化/去重/关闭等待对应现worker与probe subprocess机制；不引入样本桥接清理。 |
| `fatal_pending` 严重错误及在途防重派 | helper-fault-and-inflight-state | execution-part-excluded;diagnostics-existing — 不重派未确认主动动作的原则有据，但无主动链时不照搬84类修改事务状态；当前失败可见。 |
| `logging` 诊断日志 | local-diagnostic-files | existing-equivalent — 阶段/PID/原始错误/完整栈与notes/journal已有；日志辅助不是独立地图功能。 |
| `numeric_validation` 数值与字段验证 | pure-validation-plus-write-readback | existing-equivalent — 有限数值、Decimal、类型/原始字节诊断已在；写后读回分支不采用。 |
| `selftest` 打包运行时自检入口 | loads-target-dll | excluded-target-execution;own-tests-existing — 样本runtime-self-test装载helper，未运行；项目自己的可信隔离测试已有。 |
| `cli` 53个CLI参数及特殊自检分支 | mixed-cli-dispatch | existing-read-entrypoints;writes-excluded — 53参数逐项保留实际run_cli上下文。状态/读取可能走helper；设置参数不因CLI形式成为只读。 |

## Full hotkey disposition

| ID | Label | Effect | Current disposition |
| --- | --- | --- | --- |
| `read_unit` | Ctrl+F11  读取所有选中单位 | active-helper-read | existing-local-probe;global-registration-optional |
| `hero_level` | Ctrl+Q  英雄等级 | game-mutation | excluded-mutation |
| `instant_move` | Ctrl+X  瞬间移动 | game-mutation | excluded-mutation |
| `explode_unit` | Ctrl+W  瞬间爆炸目标单位 | game-mutation | excluded-mutation |
| `reveal_map` | Home  开图 | game-mutation | excluded-mutation |
| `hide_map` | End  关图 | game-mutation | excluded-mutation |
| `invulnerable` | Ctrl+E  无敌 | game-mutation | excluded-mutation |
| `vulnerable` | Ctrl+R  取消无敌 | game-mutation | excluded-mutation |
| `reset_cooldown` | Ctrl+Z  重置冷却 | game-mutation | excluded-mutation |
| `clone_to_self` | Ctrl+A  复制单位给自己 | game-mutation | excluded-mutation |
| `duplicate_inventory` | Ctrl+D  复制背包物品 | game-mutation | excluded-mutation |
| `unit_scale` | Ctrl+P  设置大小 | game-mutation | excluded-mutation |
| `item_charges` | Ctrl+F  物品数量 | game-mutation | excluded-mutation |
| `drop_inventory` | Ctrl+T  丢弃背包所有物品 | game-mutation | excluded-mutation |
| `add_ability` | Ctrl+G  添加技能 | game-mutation | excluded-mutation |
| `clone_unit` | Ctrl+B  复制单位 | game-mutation | excluded-mutation |
| `take_control` | Ctrl+I  获取对方控制权 | game-mutation | excluded-mutation |
| `add_resources` | Ctrl+L  增加金币木材 | game-mutation | excluded-mutation |
| `mass_clone` | Ctrl+N  大量复制 | game-mutation | excluded-mutation |
| `ability_level` | Ctrl+H  光环/被动等级 | game-mutation | excluded-mutation |
| `remove_ability` | Ctrl+J  删除技能 | game-mutation | excluded-mutation |
| `all_auras` | Ctrl+Num1  全光环 | game-mutation | excluded-mutation |
| `all_passives` | Ctrl+Num2  全被动 | game-mutation | excluded-mutation |
| `six_artifacts` | Ctrl+Num3  得到6个神器 | game-mutation | excluded-mutation |
| `reinforcements` | Ctrl+K  呼叫增援 | game-mutation | excluded-mutation |
| `preset_item` | Ctrl+M  得到物品 | game-mutation | excluded-mutation |
| `preset_tech` | Ctrl+O  得到科技 | game-mutation | excluded-mutation |
| `create_all_items` | Ctrl+S  创建所有物品 | game-mutation | excluded-mutation |
| `ignore_collision` | Alt+L  无视碰撞体积 | game-mutation | excluded-mutation |
| `hero_attributes` | Alt+Q  设置属性 | game-mutation | excluded-mutation |
| `skill_points` | Alt+W  增加技能点数 | game-mutation | excluded-mutation |
| `kill_owner_units` | Alt+E  秒杀玩家的所有单位 | game-mutation | excluded-mutation |
| `xp_rate` | Alt+R  增加经验获取率 | game-mutation | excluded-mutation |
| `reset_ability` | Alt+T  重置技能 | game-mutation | excluded-mutation |
| `all_debuffs` | Alt+Y  获得 debuff | game-mutation | excluded-mutation |
| `all_buffs` | Alt+U  获得 buff | game-mutation | excluded-mutation |
| `fullscreen_swarm` | Alt+I  全屏腐臭蜂群 | game-mutation | excluded-mutation |
| `fullscreen_clap` | Alt+O  全屏雷霆一击 | game-mutation | excluded-mutation |
| `fullscreen_monsoon` | Alt+P  全屏季风 | game-mutation | excluded-mutation |
| `fullscreen_starfall` | Alt+A  全屏群星陨落 | game-mutation | excluded-mutation |
| `fullscreen_forked` | Alt+S  全屏叉状闪电 | game-mutation | excluded-mutation |
| `fullscreen_auto` | Alt+D  全屏自动特效攻击 | game-mutation | excluded-mutation |
| `toggle_unit_pause` | Alt+F  暂停/恢复单位 | game-mutation | excluded-mutation |
| `toggle_game_pause` | Alt+G  暂停/恢复游戏 | game-mutation | excluded-mutation |
| `end_game` | Alt+H  结束游戏 | game-mutation | excluded-mutation |
| `remove_all_abilities` | Alt+J  技能全删 | game-mutation | excluded-mutation |
| `ally_health_lock` | Alt+K  我方锁血 | game-mutation | excluded-mutation |
| `allied_cooldowns` | Alt+C  重置我方全部技能冷却 | game-mutation | excluded-mutation |
| `rapid_build` | Alt+V  快速建造/研究 | posted-cheat-input | excluded-mutation |
| `instant_victory` | Alt+B  直接胜利 | posted-cheat-input | excluded-mutation |

## Actual active read prerequisite

`_selected_candidates_snapshot → persistent_native_selected_snapshots → persistent_native_init/_run_native_helper_ops → _ensure_native_helper_persistent_hook → LoadLibraryW/GetProcAddress/SetWindowsHookExW`. Ability/item field reads, resource lists and mouse-world queries join `_run_native_helper_ops`. Fourteen source steps were checked against the bound instruction records; full call sites are retained. Get/Read naming is not passive-read proof.

## Applied gap and verification

R8 item metadata exposed a real error in current source: the curated `iclb` label said loot/drop while the independently generated project table declares blue tint; `ifil` said replacement list while it declares a model path. Reviewing all 85 curated overrides found 17 definite role corrections covering attack count/timing, food, view range, casting timing, model/tint, legacy level and upgrade time. Exact category-qualified WESTRING evidence resolves the stale generated uhos translation as neutral-hostile display, not attack behavior. All other synonymous and unresolved legacy keys are preserved. No target dictionary was copied.

`field-label-audit.json/.md` lists all 85 decisions. `field-label-implementation.json` records two product hashes, the 58-pass focused scope, Ruff/format/basedpyright/syntax/whitespace gates, red-to-green tests and scope limitations. Tests parse four encoded synthetic Warcraft object tables, materialize/export all 21 fields and call the actual reference CLI; they retain original values, full tab/newline/quote text and file provenance.

## Full supplemental ledgers

- `feature-parity.json`: all 37 families, every original evidence pointer and current source anchors/hashes.
- `hotkey-parity.json`, `cli-parity.json`, `ui-declaration-parity.json`: all 50/53/285 entries with original static handler/call context.
- `ability-field-parity.json`, `item-field-parity.json`, `unit-field-sites-parity.json`, `id-catalog-parity.json`: all 753/20/53/1950 records.
- `module-parity.json`, `code-coverage-parity.json`, `native-range-parity.json`: all 7/1112/136 supporting entries.
- `identity-binding.json`, `carchive-bound-inventory.json`, `pyz-bound-inventory.json`, `firstparty-code-binding.json`, `prior-evidence-manifest.json`: complete byte/container/evidence binding.

## Remaining scope

R8 has no observed first-party MPQ/CASC/map/save/GameCache extraction workflow; those capabilities must not be attributed from another trainer sample. Existing GameXRay ID import, save workspace, savecodes inputs, hotkeys inspector and SLK evidence were not counted again. Optional UI gaps are full bilingual wording/independent term hover and a global shortcut that only triggers a passive probe. Reforged runtime fields and mouse world coordinates still require independent build/layout/real-game proof. No current values or offsets were invented. Target DLL, bytecode, scripts and self-test were never run; no original assets were uploaded or edited.
