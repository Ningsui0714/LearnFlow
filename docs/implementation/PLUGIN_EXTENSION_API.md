# LearnFlow 插件扩展 API v1

LearnFlow 第一版插件不是独立应用、工作台、进程或数据库。它是随 LearnFlow 一起加载的受信 Agent 工程包，
只向现有 Tutor 对话贡献四类能力：Tool、Agent Skill、Plugin Object 和 Tool Renderer。

```text
plugin manifest
  ├─ objects[]      版本化 JSON 对象合同
  ├─ tools[]        模型工具 schema、路由条件与本地 handler
  ├─ skills[]       使用条件、禁止条件、说明及 tool/object 引用
  └─ renderers[]    工具结果的客户端组件声明

Tutor Agent
  ├─ 合并已启用插件的 Tool definitions
  ├─ 把已启用插件的 Skill instructions 放入本轮上下文
  ├─ 调用 namespaced handler 并校验 Plugin Object
  └─ 把结果作为 TutorToolRun 回灌模型和对话

conversation ToolRun
  └─ renderer id → 插件组件；缺少组件 → 通用对象卡
```

## 1. Tool

每个 Tool 声明稳定局部 ID、标题、功能描述、正反路由条件、严格输入 schema、输出对象类型、可选 renderer
以及本轮适用的 Tutor mode。宿主把模型可见名称确定性限定为 `plugin_id__tool_id`，插件和核心工具不会
共享未限定命名空间。

第一版只接受 `read_only` 和 `artifact` 风险等级。插件 Tool 不能写五核、EvidenceEvent、LearnFlow 核心对象，
也不能批准自己的产物。输入拒绝额外字段；输出必须是有界 JSON，失败以结构化 ToolRun 返回。

Tool 描述必须同时说明“何时使用”和“不要用于什么”。插件数量增加时，宿主只暴露默认启用或本轮显式
启用的包，不把所有插件 schema 常驻塞入模型上下文。

## 2. Agent Skill

插件 Skill 是 Agent 工程里的操作说明，不是 LearnFlow 的教学法状态机，也不是第四类主 Agent。它声明：

- 何时使用、何时禁止；
- 本轮有界 instructions；
- 所引用的同包 Tool 和 Object type。

宿主只在插件启用时把 Skill 放入 Tutor 上下文，并自动把工具名限定到插件命名空间。Skill 不能改变评分、
掌握判定、LearningSkillRun、EvidenceEvent 或五核归约规则。

## 3. Plugin Object

Tool 返回的领域对象使用不可变信封：

```json
{
  "protocol": "learnflow.plugin-object.v1",
  "pluginId": "example_plugin",
  "objectType": "node",
  "objectId": "node:42",
  "schemaVersion": "example.node.v1",
  "label": "节点 42",
  "value": {}
}
```

宿主检查对象归属、声明类型、schema version、JSON 有限值、包内 validator 与总输出大小。Plugin Object
是工具结果中的事实边界，不自动成为 LearnFlow 数据库对象、学习证据、学习者画像或掌握状态。以后若需要
持久化，应另行设计明确的核心对象转换/确认接口，而不是扩张本协议。

## 4. Tool Renderer

Tool 可以在 manifest 中声明一个 renderer，并在成功结果中请求该 renderer。宿主把 renderer 限定为
`plugin_id:renderer_id`，对话中的通用 `PluginToolResultView` 根据注册表选择客户端组件。

Renderer 只获得已校验的 Tool result 和 Plugin Object；接口不提供工具调用、核心状态写入或 HTML/脚本注入。
找不到组件时，宿主显示通用对象卡和转义后的 JSON，不丢失结果。这让雷达图、事理森林、领域卡片等表现
由插件包自行实现，LearnFlow 主界面不出现岗位名称、对象类型或 renderer 的条件分支。

Renderer 还可以使用宿主提供的通用 `onPrompt(prompt)` 回调，把用户点击的对象和快照引用写入当前输入框。
该回调不发送消息、不调用工具、不改变插件数据或核心对象；用户仍需编辑或发送下一轮消息。Tutor 的近期
ToolRun 投影会有界保留 `presentation.state` 和最多 16 个 Plugin Object，支持代词式追问继续固定原快照。

宿主还提供两个不增加扩展点的确定性交互：`onReference(object)` 只接受已校验的 Plugin Object，并通过
`application/x-learnflow-plugin-object` 拖拽载荷或点击操作把 `pluginId + objectType + objectId + schemaVersion`
放入当前草稿；宿主会重新要求该引用命中当前可见 ToolRun 中的已校验对象，不信任任意外部拖拽 JSON。
`onOpenPaper()` 把产生当前结果的原 ToolRun 作为只读投影附到对话纸张。引用不会自动发送，
纸张不会复制 Plugin Object 的领域权威，两者都不能触发工具、Action、EvidenceEvent 或五核写入。视图切换
属于插件 Renderer 内部状态，例如同一岗位全景结果可以切换为能力雷达或对象卡片；宿主不理解这些视图语义。

## 5. 包目录与发现

内置插件放在 `frontend/plugins/<plugin_id>/`：

```text
server.ts       manifest + handlers，导出 default 或 plugin
client.tsx      renderer components，导出 default 或 plugin
```

服务端按目录排序发现 `server.ts/js/mjs`；客户端使用构建时 glob 发现 `client.tsx`。宿主代码不维护插件 ID
列表。包必须通过 `defineLearnFlowPlugin()` / `defineLearnFlowPluginClient()` 暴露贡献。缺少目录等价于没有
安装插件，不改变 Tutor 核心行为。

开发态服务端以整个插件目录的文件指纹作为加载版本，并由 `versionedPluginModuleUrl()` 把同一版本令牌传给
插件内部动态依赖。这样 manifest、runtime 与共享常量只会作为同一依赖图切换，不会把新入口和旧模块缓存
混合。生产态仍在进程生命周期内只加载一次不可变目录。

客户端包还可以声明 `name / description / icon` 展示元数据。通用 `PluginCapabilityPicker` 根据同一个构建时发现结果在
对话选项栏呈现插件，选择只形成当前对话的 `activePluginIds`；宿主不按插件 ID 添加按钮、文案或状态分支。
显式启用但尚未产生工具记录的插件仍可关闭；一旦插件完成或尝试过一次 namespaced Tool，宿主会从主对话及
纸张中的 `TutorToolRun` 确定性恢复其 `pluginId`，并把它单调合并进以后每轮的激活集合。选择器此后显示
“已使用 · 锁定”，不能单独取消；删除整个对话才结束这项上下文。该规则也覆盖失败 ToolRun，并同时在客户端
恢复层与 Tutor 运行时执行，不能通过刷新、切换纸张或省略 `activePluginIds` 破坏历史可重放性。

## 6. 首个官方消费包

`frontend/plugins/role_capability_graph/` 是首个官方实现，只消费已发布的不可变 Static Role Package：

- 十个只读 Tool：目标级岗位全景、能力雷达、精确读取、岗位检索、关系查询、事理追踪、证据检查、岗位包审计、包目录与版本比较；
- 一个 `role_capability_graphing` Agent Skill；
- 岗位对象、关系、证据、审计和快照五类 Plugin Object；
- 岗位全景、岗位卡片、能力雷达、岗位关系图、事理森林、证据、审计、包目录和版本比较九个 Tool Renderer。

插件 runtime 按自身数据目录发现包并校验 manifest 中全部组件 SHA-256，包括 views、retrieval-index、
object-index、snapshot 与 reference-migrations；代码不写具体岗位、对象 ID 或快照 ID。
每次返回都固定 `packageId + packageVersion + snapshotId + rootHash`，显式披露截断与覆盖。它不包含原系统的
冷启动、迭代、工作区实例化、发布、Tag、回滚或 Registry；这些能力不能伪装成只读 Tool 或提示词 Skill。

## 7. 当前边界

- 这是受信、随应用发布的本机代码包，不提供第三方下载、签名、runner、沙箱或热安装。
- 没有 Plugin Instance、Snapshot、独立工作台、专用侧栏或插件数据库。
- “展开到新纸”只是既有 ToolRun 的对话内只读投影，不是 Plugin Snapshot 持久化对象或独立工作台。
- `defaultEnabled` 只适合官方内置能力；其他包必须由调用方传入 `activePluginIds`。
- Web Tutor 已具备 Tool/Skill 执行入口；Desktop 正式 Agent 在接入同一包加载器前不会自动执行前端插件 Tool。
- 特殊显示只位于对话 ToolRun 内，不形成第二套产品导航。

协议权威由 `backend/app/services/architecture_registry.py::PLUGIN_EXTENSION_POINTS` 和
`frontend/src/plugin-api.ts` 共同约束；测试必须覆盖命名空间、未启用状态、输入边界、对象归属、renderer
声明、重复 ID 和通用降级显示。
