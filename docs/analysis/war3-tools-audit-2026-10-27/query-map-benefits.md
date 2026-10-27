> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# 直接帮助地图解析与包查询的方向

以下按使用场景聚合，链接完整逐记录对照；不是新增实现清单或可运行代码。

- **P0 字段名、别名、类型与适用性参考**：直接受益于pack-query item/skills/units/tech/search与GUI字段说明。先加离线数据/说明，不把753/20目录变成实时getter承诺；词库3395需来源/许可核查。
  对照记录：ability_catalog、item_fields、hover_dictionary、target-3/catalog_resources/t3.catalog.ability-fields、target-3/catalog_resources/t3.catalog.item-fields、target-3/catalog_resources/t3.catalog.field-labels。

- **P0 带build/来源的对象与技能装备目录**：项目已有对象与完整字段搜索；可补独立版本参考视图。保留map自定义优先/类别case-sensitive/rawcode，目录存在不等于地图加载。1950旧新数据相同，不重复当新能力；CASC catalog不是reader。
  对照记录：id_catalog、target-3/catalog_resources/t3.catalog.id-catalog、target-3/catalog_resources/t3.catalog.descriptions、target-3/catalog_resources/t3.catalog.id-search、target-3/catalog_resources/t3.catalog.official-equipment、target-3/catalog_resources/t3.catalog.hero-skills、target-3/catalog_resources/t3.catalog.casc-data。

- **P1 隐式资源路径作为可验证候选**：1191条路径可补外部listfile/资源发现，只按当前归档实读确认；未知块和完整性缺口仍保留。不要搬260字节、成员大小/显示数量的任意全局上限。
  对照记录：target-3/catalog_resources/t3.catalog.mpq-names、target-3/catalog_resources/t3.catalog.mpq-path、target-3/catalog_resources/t3.catalog.mpq-read。

- **P1 JASS直接前向调用/引用诊断**：利用现有原始语言视图、函数/调用索引，增加可定位源行的静态检查；不执行JASS，也不把Lua/未知语言套同规则。
  对照记录：target-3/catalog_resources/t3.catalog.jass-order。

- **P1 更完整文本载体存码线索**：文本模板读取已有，可补prefix/Preload/Tooltip候选和出处；MEM_PRIVATE ASCII/UTF16运行时扫描另列适配，不假装已具备或当前地图合法。
  对照记录：target-3/catalog_resources/t3.catalog.save-code-text、target-3/catalog_resources/t3.catalog.save-code-memory。

- **P1 英雄缓存/嵌入存档的完整结构解析**：这是最直接的新增离线解析方向之一：现已有容器和键/对象字节证据，需新schema、唯一shape与完整字节消费、所有raw_offset/尾部。属于需要适配，未实现。
  对照记录：target-3/catalog_resources/t3.catalog.save-container、target-3/catalog_resources/t3.catalog.cache-fields、target-3/catalog_resources/t3.catalog.cache-layout、target-3/catalog_resources/t3.catalog.embedded-cache。

- **P0 全量记录、分母与结构化错误**：保持项目0=全量与完整诊断；拒搬Web前200目录/前100文件、选择24/64/12、nodes8192、string256等wire/经验ceiling。协议容量需续传或显式不完整；真实字段字节/物理槽位与分配安全边界继续保留。
  对照记录：limits、target-3/ui/desktop.limit-catalog、target-3/ui/desktop.limit-archive、target-3/catalog_resources/t3.catalog.errors。

- **P0 完整选择集合与现有静态查询联动**：沿GameXRay自己的已验Classic handle-pair选择链收全selected_units；已有item/skills/doc/near/where可解释已读四码与坐标。69runtime字段只有8条现能力对应，余61条需新布局。
  对照记录：selection、selection_set、rawcodes。
