import type { AgentEvent } from "@/lib/agent/events";

export function assistantMessageFromEvents(input: { references: unknown[]; events: AgentEvent[] }) {
  const answer = input.events.filter((event) => event.kind === "answer.delta").map((event) => String(event.payload.delta || "")).join("")
    || String(input.events.findLast((event) => event.kind === "answer.completed")?.payload.answer || "");
  const reasoning = input.events.filter((event) => event.kind === "reasoning.delta").map((event) => String(event.payload.delta || "")).join("")
    || String(input.events.findLast((event) => event.kind === "answer.completed")?.payload.reasoning || "");
  const citationEvent = input.events.findLast((event) => event.kind === "citation.registry");
  const failed = input.events.findLast((event) => event.kind === "run.failed");
  const activities = new Map<string, { id: string; label: string; detail: string; status: "running" | "done" | "failed" }>();
  const labels: Partial<Record<AgentEvent["kind"], [string, string]>> = {
    "run.started": ["run", "开始分析问题"],
    "snapshot.pinned": ["snapshot", "固定岗位快照"],
    "plan.created": ["plan", "生成检索与组装计划"],
    "coverage.checked": ["coverage", "检查证据覆盖"],
    "context.assembled": ["context", "组装语义与事理上下文"],
    "reasoning.completed": ["reasoning", "模型思考过程"],
    "answer.completed": ["generation", "模型原样输出"],
  };
  for (const event of input.events) {
    if (event.kind === "tool.started" || event.kind === "tool.finished" || event.kind === "tool.deduplicated") {
      const name = String(event.payload.name || "unknown");
      activities.set(`tool:${name}`, { id: `tool:${name}`, label: name, detail: event.kind === "tool.started" ? "正在读取项目岗位包" : `${Number(event.payload.returned || 0)} 项`, status: event.kind === "tool.started" ? "running" : event.payload.ok === false ? "failed" : "done" });
      continue;
    }
    const label = labels[event.kind];
    if (label) activities.set(label[0], { id: label[0], label: label[1], detail: "", status: "done" });
  }
  if (failed) activities.set("run", { id: "run", label: "运行未完成", detail: String(failed.payload.message || ""), status: "failed" });
  return {
    text: answer || String(failed?.payload.message || ""),
    reasoning,
    references: input.references,
    activities: [...activities.values()],
    citations: Array.isArray(citationEvent?.payload.citations) ? citationEvent.payload.citations : [],
    status: failed ? (/取消/.test(String(failed.payload.message || "")) ? "cancelled" as const : "failed" as const) : "done" as const,
  };
}
