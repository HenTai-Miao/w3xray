# AGENTS.md

## Scope
- Applies to `/Users/zhongerbing/Documents/xm/war3_xg/w3xray` and descendants.
- Python 3.14+ project managed by `uv`; GUI uses CustomTkinter, map MPQ parsing is Python, and Windows CASC support uses pinned CascLib sources.
- Preserve unrelated dirty work. Never execute historical binaries, DLLs, or map payloads; source maps are read-only inputs.

## Orientation
- `main.py`: default GUI plus `description-cache`, `integrity`, `cli`, `guide`, `current`, `casc`, `save`, `acceptance`, and `batch` dispatch.
- `w3xtool/gui.py`, `gui_topbar.py`, `gui_lifecycle.py`: GUI composition, top-level actions, and shutdown.
- `w3xtool/cli_options.py`, `api.py`, `archive_source.py`: existing map CLI, load/export API, and archive boundary.
- `w3xtool/guide_report.py`, `guide_cli.py`: one-shot player-facing guide report (basic info, chat commands, quest texts, hero lineup, recipes, shops, drops, wave clues) behind the `guide` subcommand.
- `w3xtool/live_inventory.py`, `live_handle_chain.py`, `live_cli.py`: read-only live game memory reader behind the `live` subcommand — currently selected unit's inventory plus every item-bearing unit on the map (handle-system chain, version offsets in `HANDLE_CHAIN_OFFSETS`); `--players` lists every player-owned unit with owner slot and coordinates (unit struct +0x58/+0x284/+0x288, validated on 1.27.0.52240/KK; oversized owner slots are salvaged from item-bearing units), and unit/selected/match entries carry live x/y coordinates; `--resources <gold> <lumber>` calibrates against the caller's HUD values and lists every player's gold/lumber/food (same-layout float structs, food best-effort), plus an authoritative per-slot chain section labeled `玩家N(name)` with a `<-- 你` local marker (names via `--nick 大厅号=名字`, hero codes as fallback, re-read fresh every run). Mandatory per AGENTS.d/live.md: every user question about the live game must re-probe the running process/map fresh — never answer from a previous reading (games end or switch between questions).
- `w3xtool/pack_query_cli.py`: one-process knowledge-pack query behind the `pack-query` subcommand (item/recipe/where/drop/quest/text/price/shop) — use it instead of writing throwaway analysis scripts into temp folders (shell change notifications from churn freeze Explorer).
- `w3xtool/cache_root.py`, `guide_cache.py`, snapshot cache in `client_object_data.py`: fail-open disk caches outside the repo (content-addressed client snapshots, per-map guide reports). Env: `W3XRAY_CACHE_DIR`, `W3XRAY_SNAPSHOT_CACHE=0`, `W3XRAY_GUIDE_CACHE=0`.
- `w3xtool/object_materialization.py`: pure per-object materialization; `W3XRAY_MATERIALIZE_WORKERS>1` enables process-pool parallel merge (serial fallback on any failure); the `guide` CLI auto-sets it to min(8, cores).
- `w3xtool/save_container.py`: bounded read-only `.w3z`/`.w3v` recorded-save container decoding (checksums verified, no repacking).
- `w3xtool/current_map_models.py`: typed evidence and pure confidence resolution.
- `w3xtool/current_map_process.py`, `current_map_probe_command.py`, `current_map_inuse_probe.py`: bounded OS process/open-file/in-use-file probes.
- `w3xtool/current_map_discovery.py`: bounded roots, recent cache/`.wgc`/game-log hints, and orchestration.
- `w3xtool/current_map_snapshot.py`, `current_map_snapshot_cleanup.py`: stable private copies and owned cleanup.
- `w3xtool/current_map_cli.py`, `gui_current_map.py`, `gui_current_map_worker.py`, `gui_current_map_presenter.py`: CLI/GUI current-map entry, worker, and presentation.
- `w3xtool/batch_cli.py`, `batch_runner.py`, `batch_map_processing.py`: sequential resumable map-directory extraction.
- `w3xtool/batch_manifest_*.py`, `batch_publication_*.py`: per-map content manifests, durable transactions, validation, and crash recovery.
- `w3xtool/batch_global_*.py`, `batch_resume.py`: authoritative immutable generations, `current.json`, checkpoints, and verified reuse.
- `w3xtool/batch_execution.py`, `batch_runtime.py`: isolated map workers, cancellation/timeouts, disk/RSS preflight, progress, and diagnostics.
- `w3xtool/integrity_snapshot*.py`, `integrity_cli*.py`: explicit read-only root snapshots, verification, and CLI boundaries.
- `w3xtool/integrity_report_*.py`: append-only manifested history for overwritten integrity reports.
- `w3xtool/description_cache_retained_*.py`: descriptor-relative, no-follow, two-round retained-cache evidence scanning and canonical reports.
- `w3xtool/object_text_models.py`, `object_text_index.py`, `description_cache.py`: lossless object-text evidence, seven states, and trusted base-object fills.
- `w3xtool/item_relation_models.py`, `item_relation_builder.py`, `item_relation_exports.py`: immutable drop/acquisition/equipment-skill relations and TSV reports.
- `w3xtool/script_protection.py`: 平台加密脚本签名检测（KKWE 加密 JASS 等真图签名）；无名块导出循环内零成本嗅探并写 `未知文件/加密脚本检测.txt`，审计对无可执行语句的存根主脚本发 `script.stub` 警告——脚本被加密时脚本类分析（隐藏指令/合成/掉落触发）不可用，不得用猜测补全。
- `w3xtool/gui_item_relations.py`, `gui_item_relation_layout.py`: searchable relation workspace and evidence navigation.
- `w3xtool/gui_worker_registry.py`, `gui_worker_host.py`: bounded GUI workers and Tk-main-thread callback delivery.
- `tests/`: pytest suite; current-map coverage is in `test_current_map_*.py` and `test_gui_current_map*.py`.

## Verified Commands
- Install dev dependencies: `uv sync --dev`.
- Run GUI: `uv run main.py`.
- Run map CLI: `uv run main.py cli <map-path>`.
- One-shot map guide: `uv run main.py guide <map-path> [--section basic|commands|quests|heroes|recipes|shops|drops|clues] [--refresh]`; repeat queries hit the per-map cache (~0.5s), map edits invalidate it.
- Query an exported knowledge pack: `uv run python -X utf8 main.py pack-query <pack-dir> <item|recipe|where|drop|quest|text|price|shop|tech|cmd|refs> <查询词> [--limit N]` (single process, bounded output; `refs` classifies an object code's script references (given/created vs consumed-as-material) and warns when an item has zero consumption references — use it to adjudicate upgrade-chain termination before claiming "还能升级"; `cmd` resolves a chat command's full effect chain (registration → trigger var → condition + action function body excerpts) from `脚本可读文本/*.j` — use it instead of hand-rolled handler-digging regexes; `item` shows gold prices and `price` looks them up directly — per-item `igol` map overrides first, then `base_objects` inheritance; `tech` prints a one-screen tech sheet (max level / per-level gold+lumber cost / effect tooltips / greq prerequisites) with custom `war3map.w3q` fields overriding `base_objects`-inherited values — use it for any “这科技几级/多少钱” question instead of hand-rolled greps; `item` resolves 装备效果 from the item's `iabi`-equipped abilities' stat fields (`Istr`/`Iagi`/`Iint`; map-custom `war3map.*` rows override `base:` inherited rows, which can differ by an order of magnitude) and prefers the map's own `ides`/`utub` tooltip text over inherited base-template descriptions; `shop` lists one shop's stock with per-item real prices; `recipe` output is deduplicated).
- Locate current map: `uv run main.py current [--root PATH] [--accept-suggestion]`.
- Migrate trusted descriptions: `uv run main.py description-cache migrate --legacy-output <schema-1-root> --legacy-cache <schema-2-cache.tsv> --output <owned-cache-root>`.
- Batch schema 6: `uv run main.py batch <maps-root> --output <v6-root> --game-data <client-or-trusted-icon-root> --description-cache <owned-cache-root>`.
- Snapshot/verify inputs: `uv run main.py integrity snapshot --root LABEL=PATH --output <snapshot.json>` and `uv run main.py integrity verify --snapshot <snapshot.json>`.
- Inspect retained cache: `uv run main.py integrity retained-cache --active-root <owned-cache-root> --output <report.json>`.
- Full tests: `uv run w3xray-test` (Windows-safe); direct alternative: `uv run python -m pytest -q`.
- Maintained changed-path quality gate: `uv run w3xray-quality`.
- Focused tests: `uv run python -m pytest -q <test-paths>`.
- Lint/format changed Python: `uv run --with ruff ruff check <paths>` and `uv run --with ruff ruff format --check <paths>`.
- Type-check changed Python: `uv run --with basedpyright basedpyright --level error <paths>`; no checked-in basedpyright config.

## Knowledge
- 地图证据原则（不要猜）：只有地图里真实存在的数据才算事实。**任务/攻略文本是低可信来源**——名词与数字必须对对象表和脚本核实（实例：任务称「四象之力」实为物品「四象本源」；「恶魔20分」「宠物技能开宝箱」脚本未实现；自称17条配方实为22条），文案与实现不符时以脚本为准并向玩家标注差异；售价以 `usei`/`Sellitems` 货架为准——`igol` 只是内部估值，商店没卖就是没卖；物品效果以地图自定义 `ides`/`utub` 提示文本为准——按基础ID继承的模板描述（含 `<字段占位符>`，同名自定义物品共用）不可当作真实效果；装备加成以 `iabi` 携带技能的属性字段为准（`Istr`/`Iagi`/`Iint`），地图自定义行优先于 `base:` 继承行，两者可能差一个数量级，漏看自定义行会得出错误结论；分析导出数据必须覆盖全部自定义行，不得因输出截断而拿继承值下结论；获取途径只认真实货架、掉落表、脚本放置/奖励。回答地图问题必须引用上述真实来源，禁止用继承值或推测补全。
- 继承行语义（双行是有意设计）：`对象字段.tsv` 同时保留 `base:` 继承行与自定义行作为无损证据，读取方必须自行裁决优先级——自定义行优先、继承行兜底（如 `load_shop_stocks` 对未改货架原版商店的处理）。关系表（掉落与获取/装备技能）有意只认地图自定义 `usei`/`iabi` 行（作者证据），生效继承货架的展示走 pack-query 的兜底路径。静态检查注意：本仓库使用 Python 3.14 的 PEP 758 无括号多异常 `except A, B:` 写法，旧版解析器会误报 SyntaxError。
- 已知提取边界（记录备查，勿盲目改格式）：脚本调用参数索引的"摘要"列只取首行且截断 160 字符，多行/超长调用的参数重建依赖"参数"列而非摘要；关系构建的 legacy 回退路径（无 field_evidence 时）不解析 `名称(四码)` 括号形式。
- 玩家状态先行（先读人、再翻图、后开口；顺序不可倒置）：玩家问"接下来干嘛/怎么打/出什么装备"这类推进建议时，强制顺序＝①先 live 重探拿现状（选中英雄、背包六格、坐标、队友、资源），②用坐标对齐地图区域/章节推断进度，③用背包做"已有 vs 可达"差集，只推荐下一步**够得着**的升级（当前区域商店、当前等级能刷的掉落、原料已大半到手的配方），并给每件推荐物标注获取路径；终局 BiS 只能作为远期路线图附注，绝不作为主答案——玩家拿不到的成品不推。推荐带门槛的内容（转职/挑战场/航线/副本）前必须先核对玩家等级与进度是否已过门槛。装备/商店大盘点受闸门②约束：满量枚举后才允许下"最强"结论，截断过的盘点禁止排 BiS。
- 断言防呆四闸（回答玩家"怎么获得/打谁掉什么/一共有几个"类问题前必须全过；机制通用，不绑定具体地图名词，历史实例见 AGENTS.d/map-evidence.md 附录）：①**掉落断言前置**——"打 X 掉 Y/通关奖励 Y"必须先跑 `pack-query where <id>` 与 `pack-query drop <id>` 并引用其输出；单位身上带某物品（脚本塞给剧情 NPC 的展示道具）不构成掉落证据；掉落与获取关系.tsv 无该物品的单位死亡掉落行时必须明说"无掉落记录，仅合成/脚本奖励"。②**计数满量**——用 grep/脚本索引统计数量（Boss 个数、配方数、掉落点数）必须消费全部匹配行；grep 超出单次 250 上限时改用更窄 pattern 或按文件分片重查，禁止 `slice(0,N)` 后下结论；触发器行号顺序≠触发顺序，尾部行同样可能是关键实体。③**同名不同码**——单位同名不等于同一实体：先拿 fourcc 对当前图单位表的阵营/类型裁决身份（中立被动=剧情 NPC 站桩，不掉落；敌对槽位=战斗实体；连续 Boss 战常以另一 ID 重生同名 Boss）；随机奖池（脚本 itempool 数组）是"打怪抽奖"渠道，描述来源时写"池子 N 选 1、抽取点 M 处"而非固定掉落。④**名字与标签不是证据**——单位分类（英雄/杂兵）只认字段证据（fourcc 家族/基础ID/ustr），英文名与称号不算；物品名带 [N/M] 不证明存在下一级，升级链完整性用 `pack-query refs` 裁决（零消耗引用=终点）；兑换触发的交互形态（媒介/走近NPC/逐份充能/概率掷骰）按函数体如实描述，含随机数不写保底配方。
- `AGENTS.d/runtime.md`: schema-6 commands, protected roots, output semantics, required reports, and resume rules.
- `AGENTS.d/testing.md`: focused/full/static gates and schema-6 acceptance invariants.
- `AGENTS.d/map-evidence.md`: 玩家提问的证据闸门（闸门 0 玩家状态先行 / 掉落断言前置与交互形态 / 计数满量 / 同名不同码与分类证据 / 内存边界 / 否定断言与测量前提），含事故存档。
- `AGENTS.d/chat-style.md`: 对玩家的聊天风格与口语解析（对当前图词表做宽松匹配解析口语输入、字面未命中先扩展再否定、回答形态按问题分级、用户质疑=重查信号、局内节奏）。

## Boundaries
- Do not hand-edit caches/environments: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- Do not hand-edit packaging output: `build/`, `dist/`, `wheels/`, `*.egg-info/`.
- Treat `third_party/` as vendored; CascLib DLL/hash under `third_party/CascLib/bin/win-x64/` are generated local artifacts.
- Generated tables: `w3xtool/base_names.py`, `base_objects.py`, `westrings.py`, `jass_natives.py`, `field_meta.py`; update through their `build_*.py` generators. `base_names.py` additionally carries `BASE_NAMES_EN`/`BASE_CATEGORIES` (bilingual names and fine categories from the pinned war3-objectdata enUS snapshot), merged by `build_base_catalog.py --objectdata-dir`; rerun that merge after regenerating `BASE_NAMES`. `field_meta.py` additionally carries `GENERATED_FIELD_APPLICABILITY`/`GENERATED_FIELD_BOUNDS`/`GENERATED_FIELD_CONSTANTS` (ability-field useSpecific, min/max, common.j constant names); regenerate with `build_field_labels.py --meta-dir <metadata-slk dir> [--common-j <Reforged common.j>]` — labels/types are preserve-and-fill, the extra tables rebuild fully.
- Keep current-map discovery bounded and evidence-based.
- Live game inspection (`main.py live`) is read-only: `ReadProcessMemory`/`PrintWindow` snapshots only; never inject, never write game memory, never execute extracted binaries or map payloads. See `AGENTS.d/live.md`.
- Keep `/Users/zhongerbing/Desktop/Maps`, `map-extract-output`, `map-extract-output-v2`, `map-extract-output-v4`, and `trusted-icon-cache-classic` read-only; never use a historical root as a new-run destination.
- Generated caches, schema-6 batch outputs, logs, integrity snapshots, and acceptance reports belong outside the repository.
