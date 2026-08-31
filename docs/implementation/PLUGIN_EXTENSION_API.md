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

## 5. 包目录与发现

内置插件放在 `frontend/plugins/<plugin_id>/`：

```text
server.ts       manifest + handlers，导出 default 或 plugin
client.tsx      renderer components，导出 default 或 plugin
```

服务端按目录排序发现 `server.ts/js/mjs`；客户端使用构建时 glob 发现 `client.tsx`。宿主代码不维护插件 ID
列表。包必须通过 `defineLearnFlowPlugin()` / `defineLearnFlowPluginClient()` 暴露贡献。缺少目录等价于没有
安装插件，不改变 Tutor 核心行为。

## 6. 当前边界

- 这是受信、随应用发布的本机代码包，不提供第三方下载、签名、runner、沙箱或热安装。
- 没有 Plugin Instance、Snapshot、独立工作台、专用侧栏或插件数据库。
- `defaultEnabled` 只适合官方内置能力；其他包必须由调用方传入 `activePluginIds`。
- Web Tutor 已具备 Tool/Skill 执行入口；Desktop 正式 Agent 在接入同一包加载器前不会自动执行前端插件 Tool。
- 特殊显示只位于对话 ToolRun 内，不形成第二套产品导航。

协议权威由 `backend/app/services/architecture_registry.py::PLUGIN_EXTENSION_POINTS` 和
`frontend/src/plugin-api.ts` 共同约束；测试必须覆盖命名空间、未启用状态、输入边界、对象归属、renderer
声明、重复 ID 和通用降级显示。
