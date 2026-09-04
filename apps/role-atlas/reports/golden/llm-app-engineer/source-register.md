# 来源台账摘要

审查时点：2026-08-24。完整机器可读字段、资格理由、独立性分组与局限见 `research/golden-role-packages/llm-app-engineer/sources/source-register.json`。

## 总体构成

| 类别 | 数量 | 用途 |
|---|---:|---|
| 中国职业分类、职业标准、专业标准、监管文件 | 5 | 岗位锚点、教育映射、规范边界 |
| 风险管理框架 | 1 | 生成式 AI 风险与评测补充 |
| 企业正式岗位页面 | 10 | 市场名称、任务组合、相邻岗位与企业差异 |
| 官方技术文档与行业安全资料 | 9 | 方法、验收、工具、运行事件 |
| 真实开源 Issue | 4 | 复现、根因、重试、性能与授权的有限工作事件证据 |
| 合计 | 29 | 不以数量代替资格、独立性和适用范围判断 |

资格结果：23 个 `accepted`，6 个 `limited`，0 个来源仅因搜索命中而自动接受。

## 权威与规范来源

| ID | 来源 | 资格 | 核心定位与局限 |
|---|---|---|---|
| SRC-GOV-CLASS-2022 | [中华人民共和国职业分类大典（2022年版）](https://rsj.chifeng.gov.cn/cfsrsjgggs/202504/P020250429626704979199.pdf) | accepted / authoritative | 现行编码和职业定义；地方人社站转载官方全文 |
| SRC-GOV-AI-STD-2021 | [人工智能工程技术人员国家职业技术技能标准（2021年版）](https://rlsbj.cq.gov.cn/ywzl/zjrc/sy/zlxz/202301/P020230301347208580533.pdf) | accepted / authoritative | 应用产品集成实现方向；使用发布时旧编码 |
| SRC-GOV-GENAI-OCC-2024 | [生成式人工智能系统应用员新职业信息](https://www.gov.cn/zhengce/zhengceku/202407/P020240731502013926154.pdf) | accepted / authoritative | 生成式 AI 专项映射；不是完整分级技能标准 |
| SRC-EDU-AI-STD-2025 | [人工智能技术应用专业教学标准](https://www.moe.gov.cn/s78/A07/zcs_ztzl/2017_zt06/17zt06_bznr/bznr_zyjyzyjxbz/gdzyjy_zk/zk_dzyxxdl/dzxxdl_jsjl/202502/P020250207532415004946.pdf) | accepted / authoritative | 专业面向与培养要求；不等同单一企业岗位 |
| SRC-REG-GENAI-2023 | [生成式人工智能服务管理暂行办法](https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm) | accepted / authoritative | 监管适用范围；内部应用不能一概而论 |
| SRC-STD-NIST-600-1 | [NIST AI 600-1](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence) | accepted / authoritative | 自愿风险框架；不是中国法律义务 |

## 企业岗位样本

| ID | 企业岗位 | 资格 | 使用边界 |
|---|---|---|---|
| SRC-JD-BYTEDANCE-APP-BACKEND | [字节：大模型应用后端工程师（Agent方向）](https://jobs.bytedance.com/experienced/position/7536149766817138951/detail) | accepted | 互联网营销与后端规模化语境 |
| SRC-JD-DIDI-LLM-ENGINEERING | [滴滴：高级研发工程师—大模型工程](https://talent.didiglobal.com/social/p/61344) | accepted | 偏后端和大规模在线服务 |
| SRC-JD-CSSC-LLM-APP | [中国船舶：大模型应用工程师](https://cssc.zhiye.com/zpdetail/311136216) | accepted | 高学历、科研、私有化部署组合较强 |
| SRC-JD-LIZHI-LLM-APP | [荔枝：大模型应用工程师](https://jobs.lizhiinc.com/job/social/detail/7576911295640095018.html) | accepted | 前端、微调、低代码只列优先项 |
| SRC-JD-FANRUAN-APP-ALGO | [帆软：高级大模型应用算法工程师](https://join.fanruan.com/social/detail?id=9857) | accepted | 高级、偏 Agent 平台内核 |
| SRC-JD-FUDAN-LLM-APP | [复旦类脑研究院：AI大模型应用开发工程师](https://hr.fudan.edu.cn/86/ec/c15370a755436/page.htm) | accepted | 科研院所，含组织特定多模态职责 |
| SRC-JD-WIZARD-LLM-APP | [Wizard Quant：大模型应用开发工程师](https://www.wizardquant.com/career/745) | limited | 动态正文仅由检索提取，量化与推理要求偏强 |
| SRC-JD-JD-AI-INFRA | [京东：AI infra/Agent研发工程师](https://zhaopin.jd.com/web/job-info-detail?requementId=221515) | accepted | 相邻岗位，只用于平台边界比较 |
| SRC-JD-TENCENT-ALGO | [腾讯：理财通AI算法工程师](https://careers.tencent.com/jobdesc.html?postId=2076924809798922240) | limited | 动态提取，金融算法组合职责较宽 |
| SRC-JD-MEITUAN-APP-ALGO | [美团：大模型应用算法工程师](https://zhaopin.meituan.com/web/position/detail?highlightType=campus&jobUnionId=4215619700) | limited | 实习与搜推算法语境，只作相邻比较 |

## 技术与工作实践来源

| ID | 来源 | 资格 | 使用边界 |
|---|---|---|---|
| SRC-TECH-ANTHROPIC-AGENTS | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | accepted | 支撑工作流/Agent边界和最小复杂度，不证明市场普遍性 |
| SRC-TECH-ANTHROPIC-CONTEXT | [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | accepted | 与上一来源同一发布者，不重复计独立市场证据 |
| SRC-TECH-OPENAI-EVALS | [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | accepted | 支撑评测流程；示例阈值不作通用门槛 |
| SRC-TECH-MS-RAG | [Azure RAG information-retrieval phase](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval) | accepted | 指标概念可迁移，产品配置不可直接泛化 |
| SRC-TECH-MCP-TOOLS | [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | accepted | MCP 工具规范，不是所有集成的唯一方式 |
| SRC-TECH-OWASP-AGENCY | [OWASP Excessive Agency](https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM06_ExcessiveAgency.html) | accepted | 安全风险清单，不是法律规范 |
| SRC-TECH-LANGGRAPH-INTERRUPTS | [LangGraph interrupts guidance](https://langchain-ai.github.io/langgraph/concepts/breakpoints/) | accepted | 框架特定实现，只抽取可迁移原则 |
| SRC-TECH-HF-PEFT | [PEFT LoRA guide](https://huggingface.co/docs/peft/main/conceptual_guides/lora) | accepted | 只支撑条件性适配知识 |
| SRC-TECH-VLLM-METRICS | [vLLM Production Metrics](https://docs.vllm.ai/en/latest/usage/metrics/) | accepted | 只适用于 vLLM 变体，不作通用平台要求 |

## 公开工作事件

| ID | 事件 | 资格 | 不得外推的内容 |
|---|---|---|---|
| SRC-ISSUE-LANGGRAPH-7417 | [长工具调用重执行报告](https://github.com/langchain-ai/langgraph/issues/7417) | limited | 具体时长、根因、频率和所有部署 |
| SRC-ISSUE-LANGCHAIN-37619 | [异步检索器 NotImplementedError](https://github.com/langchain-ai/langchain/issues/37619) | limited | 单组件缺陷不能代表 RAG 一般故障率 |
| SRC-ISSUE-VLLM-41306 | [特定 MoE 模型性能回退](https://github.com/vllm-project/vllm/issues/41306) | limited | 性能数字与结论受版本、模型、硬件、后端限制 |
| SRC-ISSUE-MCP-2902 | [无浏览器机器授权问题](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2902) | limited | 本地 HMAC 方案不是 MCP 规范结论 |
