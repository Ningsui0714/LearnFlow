"""Process-animator agent v2：讲义内容 → 可视化（动画/静态图/不生成）三态决策。

触发边界（与 Ryan 讨论定稿）：
- 全自动；默认不触发
- 动画判据：存在「可观察状态随步骤演化」（状态容器 + 状态变化 + 机械因果 + 空间增益）
- 不适合动画但有静态结构可展示 → 生成静态 SVG 图
- 其余（操作清单/配置流程/概念叙述）→ 不生成

两层架构：
1. 规则层（零成本，只做「快速拒绝」）：负向词表命中 → none；正向强信号不足 → none
2. LLM 层（最终裁决）：decision = animation | static | none，一次调用输出对应载荷

安全：LLM 输出永不可信 → SVG 白名单消毒 + 结构校验 + 上限。
"""
import json
import re
from typing import Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings

# ── 规则层词表 ──
# 负向词：操作清单/配置流程类动作，命中即「不生成」（快速拒绝，不进 LLM）
NEGATIVE_KEYWORDS = [
    "安装", "配置", "注册", "登录", "部署", "下载", "上传", "设置", "填写",
    "点击", "打开", "启动实例", "选择镜像", "克隆", "导入", "导出", "申请",
    "购买", "付费", "开通", "绑定", "环境变量", "控制台", "仪表盘", "编辑器",
]
# 正向强信号：状态变换类动词（含协议/并发等过程动作）
POSITIVE_STRONG = [
    "交换", "比较", "递归", "遍历", "传播", "传导", "收敛", "迭代", "回退",
    "滑动窗口", "指针", "入栈", "出栈", "压栈", "堆化", "旋转", "回溯",
    "分治", "归并", "置换", "前向传播", "反向传播", "梯度下降", "卷积",
    "池化", "激活函数", "状态转移", "失配", "命中",
    "发送", "接收", "回复", "握手", "请求", "响应", "切换", "调度",
    "缺页", "同步", "等待", "唤醒", "迁移", "合并", "拆分", "匹配", "溢出",
]
# 正向结构信号：状态容器/静态结构描述
POSITIVE_STRUCT = [
    "数组", "列表", "树", "图", "矩阵", "栈", "队列", "堆", "链表", "哈希",
    "状态机", "网络层", "神经元", "节点", "边", "权重",
    "架构", "结构", "模块", "组件", "依赖", "数据流", "层次", "拓扑",
    "流水线", "协议", "状态",
]

ANIMATION_PROMPT = """你是可视化决策专家。判断给定内容是否适合可视化，并按要求输出 JSON。

## 决策规则（先决策，再生成）

1. **animation（动态动画）**：存在「可观察状态随步骤演化」——同时满足：
   - 状态容器：数组/树/图/矩阵/栈/队列/堆/指针/网络层/权重等可观察结构
   - 状态变化：步骤之间状态真的在变（交换/比较/传播/收敛/递归…），不是单纯追加事实
   - 机械因果：变化由确定规则驱动，步骤顺序不可任意调换
   → decision="animation"，并生成 animation 载荷（见下）

2. **static（静态图）**：不满足动画条件，但有静态结构可展示（架构/层次/数据流/流程框图/对比），
   画成一张 SVG 图比纯文字更清晰
   → decision="static"，生成一张 SVG

3. **none（不生成）**：操作清单、安装/配置流程、概念叙述、历史叙述、经验建议等
   → decision="none"

4. **默认倾向 none**，不要为了生成而生成。拿不准就 none。

## animation 载荷（decision="animation" 时）
{"title": "...", "subtitle": "...", "legend": [["#22c55e","树边"], ...], "steps": [...]}
- steps 6-15 个，每步 {"title": "第 N 步：…", "text": "说明（中文，独立可读）", "bars" 或 "svg" 二选一}
- bars: {"values":[数字], "highlight":[索引], "pivot":[索引], "sorted":[索引], "done":[索引]}
  （highlight=当前操作黄, pivot=基准橙, sorted=已就位绿, done=已完成深绿）
- svg: 内联 SVG，viewBox 建议 0 0 640 320

## static 载荷（decision="static" 时）
{"title": "图标题", "static_svg": "<svg …>…</svg>"}
- 一张信息完整、标签清晰的 SVG 图（架构/流程/层次等）

## 输出格式（只输出 JSON，不要 markdown 代码块）
{"decision": "animation"|"static"|"none", "reason": "一句话理由", "animation": {...}|null, "static_svg": "..."|null}"""


class AnimationAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.4,
            timeout=120,
            max_retries=0,
        )

    # ── 规则层：快速拒绝（零成本） ──
    # 策略：负向词是唯一硬拒绝；其余只要有一点过程/结构特征就交给 LLM 裁决（语义判断是 LLM 的职责）
    def classify_fast(self, text: str) -> str:
        """返回 'none'（直接拒绝）或 'maybe'（交给 LLM 裁决）。"""
        if not text:
            return "none"
        if any(k in text for k in NEGATIVE_KEYWORDS):
            return "none"
        strong = [k for k in POSITIVE_STRONG if k in text]
        struct = [k for k in POSITIVE_STRUCT if k in text]
        if strong or struct:
            return "maybe"
        # 无特征词但有强过程结构线索（编号步骤/首先然后最后）→ 给 LLM 一次机会
        if re.search(r"(^\s*\d+[.、)）]|第\s*\d+\s*步|首先|然后|最后)", text, re.M):
            return "maybe"
        return "none"

    # ── SVG 白名单消毒 ──
    SVG_TAGS = {
        "svg", "g", "circle", "rect", "line", "path", "text", "polygon",
        "polyline", "marker", "defs", "title", "tspan", "ellipse",
    }
    SVG_ATTRS = {
        "fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "transform",
        "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
        "width", "height", "viewBox", "d", "font-size", "font-weight",
        "text-anchor", "font-family", "preserveAspectRatio", "marker-end", "style",
    }

    def sanitize_svg(self, svg: str) -> str:
        if not svg:
            return ""
        svg = svg[:65536]
        svg = re.sub(r"<script.*?</script>", "", svg, flags=re.I | re.S)
        svg = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", svg, flags=re.I)
        svg = re.sub(r"javascript:", "", svg, flags=re.I)

        def _clean_tag(m: re.Match) -> str:
            tag = m.group(1).lower()
            if tag not in self.SVG_TAGS:
                return ""
            kept = []
            for name, value in re.findall(r'([\w-]+)\s*=\s*("[^"]*"|\'[^\']*\')', m.group(2)):
                if name.lower() in self.SVG_ATTRS:
                    kept.append(f"{name}={value}")
            return f"<{tag}" + (" " + " ".join(kept) if kept else "") + ">"

        svg = re.sub(r"<(\w+)([^>]*)>", _clean_tag, svg)
        svg = re.sub(
            r"</(\w+)>",
            lambda m: f"</{m.group(1).lower()}>" if m.group(1).lower() in self.SVG_TAGS else "",
            svg,
        )
        return svg

    # ── 结构校验与上限 ──
    def validate_steps(self, data: Dict) -> Dict:
        steps = data.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps 为空")
        steps = steps[:30]
        cleaned = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            step = {
                "title": str(s.get("title", ""))[:80],
                "text": str(s.get("text", ""))[:2000],
            }
            bars = s.get("bars")
            if isinstance(bars, dict) and isinstance(bars.get("values"), list):
                values = bars["values"]
                if values and len(values) <= 64 and all(isinstance(v, (int, float)) for v in values):
                    step["bars"] = {
                        "values": [float(v) for v in values],
                        "highlight": [int(i) for i in bars.get("highlight", []) if isinstance(i, int)],
                        "pivot": [int(i) for i in bars.get("pivot", []) if isinstance(i, int)],
                        "sorted": [int(i) for i in bars.get("sorted", []) if isinstance(i, int)],
                        "done": [int(i) for i in bars.get("done", []) if isinstance(i, int)],
                    }
            if s.get("svg"):
                svg = self.sanitize_svg(str(s["svg"]))
                if svg:
                    step["svg"] = svg
            if "bars" not in step and "svg" not in step:
                continue
            cleaned.append(step)
        if not cleaned:
            raise ValueError("没有合法的可视化步骤")
        legend = data.get("legend") or []
        legend = [list(p) for p in legend if isinstance(p, (list, tuple)) and len(p) == 2][:8]
        return {
            "title": str(data.get("title", "过程演示"))[:120],
            "subtitle": str(data.get("subtitle", ""))[:200],
            "legend": legend,
            "steps": cleaned,
        }

    # ── LLM 层：三态决策 + 生成（一次调用） ──
    async def decide_and_generate(self, text: str) -> Dict:
        """返回 {"kind": "animation"|"static"|"none", "data": {...}|None}"""
        resp = await self.llm.ainvoke([
            SystemMessage(content=ANIMATION_PROMPT),
            HumanMessage(content=f"内容：\n{text[:4000]}"),
        ])
        raw = resp.content
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
        if m:
            raw = m.group(1)
        data = json.loads(raw)
        decision = data.get("decision", "none")
        reason = str(data.get("reason", ""))[:200]
        if decision == "animation" and data.get("animation"):
            try:
                return {"kind": "animation", "data": self.validate_steps(data["animation"]), "reason": reason}
            except Exception:
                return {"kind": "none", "reason": reason}
        if decision == "static" and data.get("static_svg"):
            svg = self.sanitize_svg(str(data["static_svg"]))
            if svg:
                return {
                    "kind": "static",
                    "data": {
                        "title": str(data.get("title", "结构图"))[:120],
                        "subtitle": "",
                        "legend": [],
                        "steps": [{"title": "", "text": "", "svg": svg}],
                    },
                    "reason": reason,
                }
        return {"kind": "none", "reason": reason}

    # ── 讲义集成入口 ──
    async def maybe_create_visual(
        self, project_id: Optional[int], checkpoint_id: int,
        section_index: int, content: str, db,
    ) -> Optional[Dict]:
        """规则快速拒绝 → LLM 裁决 → 落库。返回 {"kind", "id"} 或 None。失败/不命中不阻塞讲义。"""
        if ":::process-anim" in content:
            return None  # 已注入过（resume 场景）
        if self.classify_fast(content) == "none":
            return None
        try:
            res = await self.decide_and_generate(content)
        except Exception:
            return None
        if res["kind"] == "none":
            return None
        data = res["data"]
        from app.models.project import ProcessAnimation
        anim = ProcessAnimation(
            project_id=project_id,
            checkpoint_id=checkpoint_id,
            source="lecture",
            kind=res["kind"],
            section_index=section_index,
            title=data["title"],
            subtitle=data.get("subtitle", ""),
            legend=data.get("legend", []),
            steps=data["steps"],
        )
        db.add(anim)
        await db.commit()
        await db.refresh(anim)
        return {"kind": res["kind"], "id": anim.id}
