# vNext 对话内学习任务设计

## 产品契约

学习任务不是新页面、课程目录或掌握记录，而是当前 Conversation 中一个可恢复的原子目标。
任务只保存目标；状态由浏览器本地追加式事件队列重建。Tutor 每轮只读任务投影，不能直接推进
阶段、评分或宣布掌握。

```text
明确的“带我学/带我弄懂/带我练”
  -> 在当前对话创建任务
  -> 建立理解 -> 主动练习 -> 独立检查 -> 收束与复习
  -> 完成流程（不等于掌握）
```

普通“什么是 X”仍只进入一轮简单讲解。学生也可以先选择“带领学习”，再发送原子目标。
任务进行中仍使用原聊天输入；流程条只提供 Skill、下一步、暂停、继续、结束和事件记录，不建立
竞争性的任务详情页。

## 四个首批 Skill

| Skill | 主要动作 | 关键边界 |
|---|---|---|
| 清晰讲解 | 核心模型 → 最小例子 → 小检查 | 不能用空泛追问代替知识起点 |
| 苏格拉底追问 | 最小支架 → 一次一个关键判断 | “不知道”时补支架，不推进 |
| 费曼复述 | 学生复述 → 肯定一处 → 定位一个跳步 | 初学者先获得起点；复述不是掌握证据 |
| 示例渐隐 | 完整样例 → 补最后一步 → 增加独立部分 | 模仿和有提示完成不是独立检查 |

Skill 只改变“当前怎样教”。四个 Skill 共用同一个任务、四个阶段和事件队列；检索练习不是第五
个 Skill，而是 `practice / verify` 阶段的共同教学原则。

## 事件队列

事件只追加、带 Conversation 内递增序号。当前原型记录创建、开始、活动段进入、学生回应、
支架请求、Skill 切换、暂停、恢复和流程完成。页面刷新后从 `localStorage` 恢复并重新投影。

- 这些是 vNext 浏览器本地运行事件，不进入后端 `EvidenceEvent` 账本。
- 所有事件在架构注册表中登记为零 Kernel target。
- 普通回复不自动切换活动段；只有学生点击“下一步”才追加 `phase_entered` 导航事件。该事件不
  表示上一环节通过，更不是正式 LearningTask 的 `phase_completed`。
- “不会 / 不知道 / 要提示 / 跳过”追加支架事件，继续留在当前阶段。
- “完成流程”只表示本轮任务收束；正式能力证据未来仍必须来自独立判题的 `LearningAttempt`。

## 研究与产品依据

本设计没有把某篇论文直接翻译成固定剧本，而是取其可执行且边界清楚的共同结论：

1. Roediger 与 Karpicke 的提取练习研究显示，相比重复阅读，主动提取更有利于延迟保持。因此
   `practice / verify` 要求学生生成答案，而不是继续播放讲义。
   [原始论文](https://learninglab.psych.purdue.edu/downloads/2006/2006_Roediger_Karpicke_PsychSci.pdf)
2. Chi 等人的自我解释研究发现，能把步骤与原理联系起来的自我解释与更好的问题解决理解相关。
   因此费曼复述和样例学习都要求学生解释一个关键关系。
   [原始论文](https://doi.org/10.1207/s15516709cog1302_1)
3. Atkinson、Renkl 与 Merrill 的工作样例渐隐研究支持从完整样例平滑过渡到问题求解，而不是让
   新手立即从空白求解。因此程序性目标默认推荐“示例渐隐”。
   [论文页面](https://link.springer.com/article/10.1023/B:TRUC.0000021815.74806.f6)
4. ICAP 框架把可观察活动区分为被动、主动、建构和互动，强调仅呈现信息不足以保证认知参与。
   因此每个阶段都要求一个学生可见的小动作，同时不把界面点击误当成能力证据。
   [原始论文](https://doi.org/10.1080/00461520.2014.965823)
5. Cognitive Tutor 研究和 ASSISTments 实践都强调问题求解中的及时反馈与按需支架，但提示与独立
   完成必须区分。因此事件队列单独记录支架请求，验证提示词也禁止把有提示成功说成独立完成。
   [CMU 研究](http://pact.cs.cmu.edu/corbett/Corbett&AndersonCHI2001.pdf) ·
   [ASSISTments 官方研究](https://www.assistments.org/evidence-of-impact)
6. Khanmigo 与 ChatGPT Study Mode 的官方设计都把引导问题、分步支架、知识检查放回持续对话，
   并允许用户切换学习方式。因此 vNext 把任务控制压在输入栏上方，而不跳转到课程页。
   [Khan Academy 设计说明](https://blog.khanacademy.org/how-we-built-ai-tutoring-tools/) ·
   [OpenAI Study Mode](https://openai.com/index/chatgpt-study-mode/)
7. ALEKS 的持续“准备度识别—个性路径—周期检查”说明任务规划应考虑先备状态和后续检查；当前
   vNext 只实现最小本地版本，不复制其掌握模型。
   [ALEKS 官方说明](https://www.mheducation.com/highered/aleks/learning.html)

## 当前非目标

- 不在浏览器中判题或产生正式掌握证据。
- 不把四阶段升级成大量机械关卡。
- 不在任务创建时生成课程文件夹、讲义或题库。
- 不让模型通过回复文本改变阶段、Skill 或事件队列。
- 不把本地事件队列冒充五核、LearningTask 后端权威或长期学习者画像。
