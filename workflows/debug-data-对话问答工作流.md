# 对话问答工作流 · 调试数据
> 工作流：`workflows/current/对话问答工作流.yml`
> 生成时间：2026-08-06 · 数据来源：STU-DEMO-001 真实画像 + Java 知识库真实检索
> 用途：在星辰工作流控制台调试入口粘贴「开始节点入参」即可运行

## 一、开始节点入参（AGENT_USER_INPUT）
复制以下 JSON 到工作流调试输入的 `AGENT_USER_INPUT`：
```json
{
  "message": "什么是封装？成绩数组为什么不能直接公开？",
  "student_id": "STU-DEMO-001",
  "student_profile": {
    "name": "林同学",
    "major": "Java 面向对象程序设计实训",
    "learning_goal": "完成 Java 面向对象成绩管理实训",
    "overall_mastery": 31,
    "learning_style": "偏好案例驱动与示例先行"
  },
  "kb_text": "【封装的本质：私有字段 + 公有方法】 封装要求将内部数据声明为 private，通过 public 的 getter/setter 方法提供受控访问。例如成绩数组 scores 应保持 private，外部通过 getScores() 获取副本、setScores() 校验后写入，避免外部直接修改内部状态导致数据不一致。\n【getter 返回副本还是引用】 基本类型 getter 直接返回值即可；引用类型（数组、List）getter 应返回防御性副本或 Collections.unmodifiableList，否则调用方拿到的仍是内部引用。返回副本有性能成本，需要与封装收益权衡，但成绩数组这类可变数据必须防御。",
  "history_memory": [
    {
      "role": "user",
      "content": "我正在学 Java 面向对象，之前学了类的定义与对象创建。"
    },
    {
      "role": "assistant",
      "content": "很好，那我们从封装开始继续。"
    }
  ],
  "assistant_mode": "education",
  "source_kind": "knowledge_base"
}
```

### 字段说明
| 字段 | 值 | 说明 |
|---|---|---|
| `message` | 用户提问 | 必填，空则「解析提问与上下文」节点抛错 |
| `student_id` | STU-DEMO-001 | 学生标识 |
| `student_profile` | 画像对象 | 传给 LLM 调整讲解节奏/支架（不杜撰信息）|
| `kb_text` | 知识库检索文本 | 格式 `【标题】内容`，来源本地检索，供 LLM 引用 |
| `history_memory` | 对话历史数组 | 消解指代，避免重复回答 |
| `assistant_mode` | education / general | education=结合知识库辅导；general=通用助手 |
| `source_kind` | knowledge_base / web / none | knowledge_base=只允许引用 kb_text |

## 二、各节点预期中间输出

### 1. 解析提问与上下文（代码节点）
```text
message: 什么是封装？成绩数组为什么不能直接公开？
student_id: STU-DEMO-001
student_profile: {"name": "林同学", "major": "Java 面向对象程序设计实训", "learning_goal": "完成 Java 面向对象成绩管理实训", "overall_mastery": 31, "learning_style": "偏好案例驱动与示例先行"}
kb_text: （与入参一致，311 字符）
history_memory: [user: 我正在学 Java 面向对象...] x2
assistant_mode: education
source_kind: knowledge_base
```

### 2. 生成对话回答（大模型节点）
模型：spark 4.0Ultra（llmId=110，temperature=0.4，maxTokens=2048）
期望输出（一个合法 JSON 对象，无 Markdown 包裹）：
```json
{"answer": "封装就是把内部数据藏起来，只通过公开方法访问。你的成绩数组应该用 private 修饰，再提供 getScores()（返回副本）和 setScores()（做校验），这样外部就不能偷偷改成绩了。你之前学的 getter/setter 就是封装的标准做法。", "sources": [{"title": "封装的本质：私有字段 + 公有方法", "locator": "第 2 节：封装与访问控制"}]}
```

### 3. 校验回答输出（代码节点）
```json
{"status": "ok", "message": "（LLM answer 内容）", "ai_generated": true, "sources": [{"title": "封装的本质：私有字段 + 公有方法", "locator": "第 2 节：封装与访问控制"}], "original_question": "什么是封装？成绩数组为什么不能直接公开？"}
```

## 三、边界与容错验证用例

| 场景 | 入参要点 | 预期 |
|---|---|---|
| 空 message | `"message": ""` | 节点 1 抛 `message 不能为空` |
| 非法 JSON 入参 | 传纯文本 | 节点 1 兜底为 `{}` → 抛 `message 不能为空` |
| 无知识库命中 | `kb_text: ""` 且提问依赖课程事实 | LLM 应回答「资料未覆盖」并 `sources: []` |
| assistant_mode=general | `"assistant_mode": "general"` | LLM 走通用助手模式，不强行引导测评 |
| source_kind=web | `"source_kind": "web"` | LLM 明确提示「非已审核知识库」并引用网页来源 |
| LLM 输出非 JSON | 大模型输出纯文本 | 节点 3 兜底 answer=「知识库暂未覆盖该问题…」，status=ok |

## 四、后端对接建议（接入本工作流时）

- 前端对话页当前为「本地知识库检索回复」；接入本工作流后：
  - `message` ← 用户输入
  - `student_profile` ← `GET /api/students/{id}/portrait` 的 `identity` + `learning_style` 精简
  - `kb_text` ← `GET /api/knowledge/search?q=消息关键词` 的条目按 `【标题】内容` 拼接
  - `history_memory` ← 前端维护最近 N 轮对话
  - 返回 `final_result_json` 的 `message`/`sources` 直接渲染到对话气泡
