# LearnFlow 通用插件宿主与包协议

状态：implemented
包协议：`learnflow.plugin-package.v1`
对象引用协议：`learnflow.plugin-object-ref.v1`
架构注册表：`2026-08-30.7`

本文规定 LearnFlow 插件的运行、持久化、可选分发和产品接入边界。插件的产品定义是 Agent Package：
由 Agent、Skill、Tool、Workflow、Schema 与聊天 UI binding 组成。插件是项目作用域的领域能力扩展，
不是第四类主 Agent、第二套用户画像、任意代码注入机制或数据库扩展机制。核心注册表、项目 ownership、
Action Board、EvidenceEvent gateway 和五核 reducer 始终由宿主控制。

## 1. 产品 Package 与四层持久化对象

官方 Agent Package 随 LearnFlow 构建加载，并在通用宿主登记同进程 handler。它不需要 ZIP、签名、平台
runner 或操作员进程开关。以下四层描述的是安装/实例/数据版本，不是说每个产品插件都必须以外部进程存在：

| 层次 | 定义 | 是否承载领域事实 |
|---|---|---|
| Plugin Bundle | 可选的 `.lfplugin` 分发包；主要服务第三方安装、签名与跨部署传输 | 否 |
| Plugin Instance | 某 learner-owned Project 对已安装 release 的启用、固定版本、配置和 Host Port 授权 | 否 |
| Plugin Snapshot | 一次通过宿主验证并提交的不可变领域数据版本 | 是 |
| Plugin Object | 快照组件中的岗位、任务、能力、过程或其他领域对象 | 由 Snapshot 承载；索引只负责寻址 |

“安装”只增加可选能力；“启用”只创建项目实例；“运行”先产生候选；只有“验证并提交”才创建新快照。
禁用实例只撤下工具和 Surface，不删除历史运行、快照或引用。对象修改永远创建后继快照，不覆盖旧对象。

通用持久化对象如下：

- `PluginPublisher`：发布者公钥、信任状态与撤销时间。
- `PluginRelease`：不可变版本、manifest、签名、artifact root hash 与平台 runner 清单。
- `PluginInstance`：`learner + project + plugin_id` 唯一；保存启用状态、固定 release、配置、授权和当前快照指针。
- `PluginSnapshot`：不可变组件清单、parent、root hash、来源、校验和 provenance。
- `PluginObjectIndex`：可从快照重建的对象 ID、类型、label、component/JSON Pointer、content hash、生命周期和引用索引；不得复制领域真相。
- `PluginRun / PluginRunEvent`：workflow 合同、请求 hash、expected snapshot、RPC 轨迹、边界披露、结果与错误。

快照组件进入内容寻址的受管 artifact store；数据库只保留 hash、大小和受管位置。提交顺序必须是：

```text
临时制品
  -> schema / 引用 / 预算 / hash 校验
  -> 按 content hash 原子落盘
  -> 数据库事务创建 Snapshot 与 ObjectIndex
  -> 原子移动 Instance.current_snapshot_id
```

数据库提交失败时，实例指针不移动；未被数据库引用的制品属于可回收孤儿，不得被读作已发布快照。

## 2. 可选的 `.lfplugin` 分发包

`learnflow.plugin-package.v1` 是第三方或可导出插件的 ZIP 分发容器；它不定义 LearnFlow 内置插件的运行形态。
容器固定允许下列内容：

```text
<plugin>.lfplugin
├── manifest.json
├── signature.json
├── bin/<os-arch>/runner
├── schemas/
│   ├── config.schema.json
│   ├── workflows/*.schema.json
│   ├── objects/*.schema.json
│   └── rpc.schema.json
├── surfaces/*.json
├── README.md
├── LICENSE
└── assets/
```

`manifest.json` 必须声明稳定 plugin ID、SemVer、宿主兼容范围、三类主 Agent owner、项目作用域、
对象类型、Host Ports、workflow、只读 tool、Product Skill、Surface、零目标 event 和配置 schema。
所有插件贡献 ID 必须 namespaced，不能覆盖核心 ID、重定义三类主 Agent、声明第四类主 Agent，
也不能动态声明具有 Kernel target 的事件。

包不得包含：

- SQL migration 或 ORM adapter；
- React、JavaScript、HTML、CSS 或其他可注入宿主页面的可执行前端；
- 数据库地址、登录 token、模型密钥或其他秘密；
- 越出 manifest 的隐式工具、workflow、对象类型或事件。

导入器必须在写入 release 前拒绝 ZIP 路径穿越、绝对路径、符号链接、重复路径、缺失组件、单文件或整体
大小超限、组件 hash 不符、平台 runner 缺失、无效 SemVer/宿主范围、同版本内容冲突、核心 ID 覆盖、
无效签名、已撤销发布者以及生产环境 unsigned 包。

## 3. 外部分发的签名、信任与真实安全边界

`signature.json` 保存发布者 ID、key ID、Ed25519 签名和整个包的 canonical root hash。签名只证明：

1. 内容与签名时一致；
2. 内容由对应私钥持有者发布；
3. 当前操作员选择信任该发布者。

签名不证明代码安全。生产只运行可信且未撤销发布者签名的 release；开发环境只有管理员显式允许时
才能安装 unsigned 包，并且 Instance、Run 和 UI 必须持续标记“未受信开发包”。发布者或 release 撤销后，
现有历史仍可读取，但立即阻止该 release 的任何新 workflow/tool run。

内置 Agent Package 不经过本节的原生进程边界。外部执行支持所有部署形态，但默认关闭；操作员必须显式
启用 `trusted_signed_process`。v1 对每次第三方原生运行都
必须披露以下真实字段，界面和 API 不得隐藏或改写：

```json
{
  "execution_mode": "trusted_signed_process",
  "filesystem_isolation": false,
  "network_isolation": false,
  "secrets_isolation": false,
  "cpu_isolation": false,
  "memory_isolation": false
}
```

因此管理员承担“受信本机进程”风险；签名包不是沙箱。若未来采用 WASM 或 OCI，只替换 runner 隔离层，
不得改变 Bundle、Instance、Snapshot、ObjectRef 或 Host Port 协议。

## 4. 第三方 Runner 与 JSON-RPC

仅第三方原生插件 runner 使用 JSON-RPC 2.0 over stdin/stdout。每个 workflow 或 tool run 启动一个独立进程：

- 根据当前平台从 `bin/<os-arch>/runner` 确定性选择入口；
- 使用固定参数数组，不经 shell；
- 使用最小环境变量，不传数据库地址、登录 token 或模型密钥；
- 使用新建临时工作目录；
- 180 秒硬超时；POSIX 在超时、取消、崩溃或协议错误时终止整个进程组；Windows v1 仅能 best-effort
  终止进程组并公开 `descendant_cleanup_guaranteed=false`，不得声称完整子进程树隔离；
- 单条 RPC 消息上限 256 KiB，单次总输出上限 1 MiB；
- 最多 32 次 Host Port 调用；
- stdout 只能承载 RPC 帧，stderr 作为有界诊断记录，不参与协议。

runner 先接收带 instance、release、workflow/tool、固定 snapshot、输入 schema 版本和调用预算的启动请求。
宿主在校验调用者输入后注入只读 `plugin_configuration`，并将应用过 JSON Schema default 的配置纳入
request hash 与 Snapshot envelope；调用者不能覆盖该字段。
它可以返回候选组件、引用、解释或 proposal，也可以调用获授权 Host Port；它不能批准自己的结果、移动
实例指针、创建核心对象、写数据库或声明掌握。宿主对最终结果重新做 schema、权限、引用、hash 和预算校验。

## 5. Host Ports

插件进程只看到 manifest 已声明、Instance 已授权且当前调用所需的端口。授权按 project、plugin、release
和 port version 固定；升级时新增端口必须再次确认。端口返回最小投影，不向 runner 暴露 ORM、数据库会话
或内部服务对象。

| Host Port | 宿主提供的能力 | 写入边界 |
|---|---|---|
| `project.read.v1` | Project identity、目标和 ownership scope | 只读 |
| `source.read.v1` | 固定 `SourceVersion`、hash、健康状态和有界 Chunk | 内容标记为不可信 |
| `knowledge_baseline.read.v1` | 已确认的 `DomainKnowledgePacket` | 只读，不表示掌握 |
| `roadmap.read.v1` | Roadmap revision、节点和来源 | 不允许直接修改 |
| `checkpoint.read.v1` | 关卡与 Teaching Contract | 不允许直接修改 |
| `learning_task.read.v1` | 正式任务、计划、引用和版本 | 修改只能形成 proposal |
| `learning_file.read.v1` | answer-safe 讲义和练习投影 | 永不返回隐藏答案 |
| `learner_context.read.v1` | 按 scope 和 manifest kernel allow-list 裁剪的 `ContextPacket` | 没有 Kernel 写接口 |
| `artifact.resolve.v1` | 解析核心 `ArtifactRef` 或固定 `PluginObjectRef` | 不提供任意写入 |
| `model.generate_structured.v1` | 宿主代调模型并按声明 schema 校验 | 有预算、可审计，插件拿不到密钥 |
| `action.propose.v1` | 提交路线、任务、文件等核心变更建议 | 只生成 Action Board proposal |
| `event.record.v1` | 记录 manifest 已声明的运行事件 | 外部插件只允许零 Kernel target |

Host Port 请求必须再次检查 learner/project ownership、instance 当前 release、manifest 声明、Instance 授权、
调用预算和对象引用。来源正文以及所有外部字符串一律标记为不可信数据，不能作为宿主指令执行。
宿主同时累计本次 `source.read.v1`、knowledge baseline 与 artifact resolve 的固定读取记录；写快照时只允许
继承 base snapshot 的来源或使用这些实际读取的 SourceVersion 引用。runner 自报的额外来源或 provenance
不能进入权威 Snapshot。

## 6. 版本、引用、并发与幂等

跨模块使用统一的固定版本引用：

```json
{
  "protocol": "learnflow.plugin-object-ref.v1",
  "plugin_id": "role_capability_graph",
  "instance_id": 12,
  "snapshot_id": 35,
  "snapshot_root_hash": "<64-char lowercase sha256>",
  "object_type": "capability",
  "object_id": "capability:...",
  "schema_version": "role-capability.object.v1",
  "content_hash": "<64-char lowercase sha256>"
}
```

解析器必须同时校验 project ownership、instance/plugin、snapshot/root hash、object type/ID/schema version
和 content hash，不能把“当前快照”替换进历史引用。写 workflow 必须携带 `expected_snapshot_id`；基线已过期
返回 `409 Conflict`，不能静默重放到新版本。幂等键在 Instance 内唯一并绑定 canonical request hash；同键
同请求返回原 Run，同键不同请求返回 `409 Conflict`。

升级先以旧 release 与当前快照为输入运行兼容或迁移 workflow。只有候选通过新 release 的全部验证后，
宿主才在同一事务中切换固定 release 和 current snapshot；失败时继续使用旧 release 与旧 snapshot。
宿主启动时会把进程中断后遗留的 `running` PluginRun 标记为可审计失败；旧幂等键继续指向该失败记录，
重试必须使用新键，避免把一次未完成运行误当作仍在执行。

## 7. 宿主 API

管理端：

- `POST /api/admin/plugin-publishers`
- `GET /api/admin/plugin-publishers`
- `PATCH /api/admin/plugin-publishers/{id}`：信任、取消信任或撤销发布者
- `POST /api/admin/plugin-releases/import`
- `GET /api/admin/plugin-releases`
- `PATCH /api/admin/plugin-releases/{id}`：撤销或废弃 release

项目端：

- `GET /api/projects/{project_id}/plugin-releases`：只返回当前可启用的安全 release 投影
- `GET /api/projects/{project_id}/plugin-instances`
- `PUT /api/projects/{project_id}/plugin-instances/{plugin_id}`：启用并固定 release
- `PATCH /api/projects/{project_id}/plugin-instances/{plugin_id}`：配置、授权、升级或停用
- `POST /api/projects/{project_id}/plugin-instances/{plugin_id}/workflows/{workflow_id}/runs`
- `GET /api/plugin-runs/{run_id}`
- `GET /api/projects/{project_id}/plugin-instances/{plugin_id}/snapshots`
- `GET /api/projects/{project_id}/plugin-instances/{plugin_id}/objects`
- `GET /api/projects/{project_id}/plugin-instances/{plugin_id}/objects/{object_id}`
- `GET /api/projects/{project_id}/plugin-surfaces?slot=project.context.tabs`
- `GET /api/projects/{project_id}/plugin-tools?query=...`
- `POST /api/projects/{project_id}/plugin-tools/{qualified_tool_id}/calls`

管理端 API 必须经过 `require_admin`；项目 API 必须经过 `CurrentLearner + require_owned_project`。客户端传入的
learner ID、release manifest、对象索引或 Surface 都不是权限依据。

项目上下文中的宿主管理页使用项目 release catalog：学习者选择固定 release，逐项勾选并再次确认 Host Port，
只填写宿主支持的 primitive config schema 字段，然后启用、停用或升级。该页持续显示 trust state 与全部
未隔离边界；管理员安装/撤销能力不会下放到项目页面。

## 8. Tool 与对话

Tutor 常驻工具面只增加两个薄宿主工具：

- `discover_project_plugin_tools`：按当前项目、scope、查询描述、release 和授权，返回已启用插件的只读工具、
  输入输出 schema 与固定 snapshot 要求。
- `call_project_plugin_tool`：调用时重新按 qualified ID 执行同一发现过滤，并再次验证 project、instance、release、
  snapshot、权限和 schema。

插件工具必须先发现再调用，不能凭 plugin/tool ID 直接执行。写 workflow 或其他副作用工具永远不直接暴露
给模型；插件只能通过 `action.propose.v1` 返回带固定 `PluginObjectRef` 的 Action Board proposal。用户确认后，
宿主把 proposal 持久化为 `AgentAction(status=pending_confirmation)`；只有核心 allow-list 中已有确定性 handler
的 capability 才可进入确认链。用户确认后，由既有 Roadmap、Checkpoint、LearningTask 或 LearningFile 服务
完成写入，插件不能扩大 allow-list 或自我确认。

## 9. Surface DSL

`PluginSurfaceHost` 只渲染宿主允许的声明式组件：

`section`、`text`、`metric`、`list`、`table`、`graph`、`form`、`input`、`citation`、`status`、`action`。

安装包中的 Surface 必须只引用一个已签名的 `surfaces/*.json` definition，manifest 不得同时藏入第二份 inline
body。Surface 不允许 HTML、脚本、插件 CSS、任意 URL、动态 import 或宿主组件名。文本按普通文本转义；citation
只能解析受管引用；action 只能引用当前 release manifest 中声明的 workflow。Surface 只是 Snapshot/Run 的
投影，不保存领域事实，也不能直接触发核心对象写入。

项目内的插件操作沿用 Tutor 与项目上下文，不建立第二套路由或插件专属页面：

- 左栏展示项目已启用插件；点击插件只选择既有项目 Tutor 对话及其 `PluginChatContext`。
- Product Skill、插件状态和 workflow 确认入口位于 Composer 选项栏。
- Surface 是聊天输入控件与工具输出 renderer 的声明，不在消息区顶部建立独立插件工作台。
- 管理抽屉只负责安装、授权、配置、停用和升级；实例失效时聊天撤下相应工具与控件。

这组入口只改变宿主导航状态；权限、Surface 发现、workflow 运行与对象写入仍经过相同的通用插件 API 和宿主校验。

## 10. EvidenceEvent 与五核

插件安装、启用、读取、生成、解释、迭代、校验和禁用均不是掌握证据。外部插件只可通过
`event.record.v1` 提议 manifest 中声明且由注册表验证的 namespaced 零 Kernel target 事件。宿主调用统一
`record_event()`，插件不能创建 `KernelMutation` 或直接写 `KernelState`。

若插件对象后来被学习者确认为 Roadmap、Checkpoint 或 LearningTask，确认只证明“核心对象已创建”，
仍不证明理解或实践能力。学习状态唯一写入链保持：

```text
LearningAttempt / 已登记用户行为
  -> EvidenceEvent
  -> five_kernel_reducer
  -> KernelMutation
  -> KernelState
  -> MemoryFact -> MemoryModule -> MemoryClaim
```

## 11. 岗位能力图谱首插件

内置 `role_capability_graph` Agent Package 是该协议的首个官方产品实现，owner 为 `learning_design_agent`；
可选 `role_capability_graph.lfplugin` 只提供分发 envelope。Package 声明 role、task、
capability、knowledge_skill、claim、semantic_edge、scenario、process_event、actor、work_object、artifact、risk、
bridge 对象；`generate / explain / iterate / validate / upgrade` workflow；Product Skill
`role_capability_graphing`；项目 Surface 和两个只读对话工具。

学习者使用路径以聊天为主：项目左栏把已启用插件显示为可进入的插件项，点击后复用项目 Tutor 对话并绑定
`PluginChatContext`。Tutor 先通过 `discover_project_plugin_tools` 获得当前项目、当前实例、当前权限下的只读能力，
再用 `call_project_plugin_tool` 固定快照读取。插件选择、Product Skill、快照版本和 workflow 入口位于 Composer
对话选项栏；岗位雷达图、事理森林、对象卡片由宿主对 Snapshot 组件确定性投影为 Tutor 工具消息，不在消息区
顶部形成独立工作台，也不保存第二份领域真相。`generate` 与 `iterate` 只由选项栏确认卡调用，模型不能代替
学习者确认；项目抽屉仅负责安装、授权、配置、停用和升级。

其快照组件包括 evidence、semantic graph、process forest、views、retrieval index、validation report 和
reference migrations。解释固定精确 snapshot，执行有界检索、关系遍历和证据读取；迭代固定 base snapshot，
形成合同、检查覆盖、生成 patch、执行结构/证据/语义校验和 meaningful diff。Agent 只能提供候选，宿主验证
通过后才提交后继快照。

历史 `RoleCapabilityPackage / RoleCapabilitySnapshot / RoleCapabilityRun` 由幂等迁移转为通用 Instance、
Snapshot、ObjectIndex；旧表冻结为只读兼容源，不再双写。旧 `/api/role-capability/...` 路由以及
`read_role_capability_graph`、`explain_role_capability` 名称保留为兼容别名，内部转发通用宿主并返回
deprecation metadata。详见 `docs/implementation/ROLE_CAPABILITY_PLUGIN.md`。

为保持已经发出的岗位对象引用可解析，迁移快照沿用旧 `root_hash`，并在 validation 中以
`snapshot_root_protocol=legacy-role-root-v1` 标明兼容身份；由通用 Artifact Store 重写的组件集合另以
`component_root_hash` 校验。所有原生通用快照仍使用完整 snapshot-envelope hash。

## 12. 验收不变量

- Bundle 校验能拒绝穿越、符号链接、超限、缺件、hash/signature/version/信任错误。
- Runner 的固定 argv、环境清理、预算、超时、取消、崩溃和全部 `isolation=false` 可观测且可测试。
- Snapshot 不可变；ObjectIndex 可重建；ObjectRef 固定精确版本。
- 除明确标记的 legacy 迁移快照外，Snapshot root 是 schema、release、组件清单、固定来源、配置与稳定校验/provenance 的宿主 envelope hash；
  组件 root 相同但这些不可变元数据不同仍形成后继版本。
- expected snapshot 与幂等 request hash 的冲突均返回 `409`。
- 升级失败不改变 release 或 snapshot 指针，禁用不删除历史，撤销阻止新运行。
- Surface 不执行插件代码；工具发现只返回当前项目已启用且获授权的只读能力。
- 所有副作用经过 Action Board proposal；所有插件事件为零 Kernel target。
- 岗位生成、解释、迭代、迁移和阅读均不产生 `KernelMutation`。
