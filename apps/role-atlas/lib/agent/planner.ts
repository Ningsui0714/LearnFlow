import type { AgentRequest } from "./events";
import type { RoleToolCall } from "@/lib/role-package/types";
import { CORE_ROLE_TOOL_NAMES, CORE_TOOL_PURPOSES, type CoreRoleToolName } from "./snapshot-runtime";

const patterns = {
  evidence: /证据|来源|引用|可信|充分|依据|溯源|矛盾/i,
  graph: /关系|关联|依赖|前置|路径|上下游|图谱|邻居|比较|区别|异同|差异|vs|versus/i,
  process: /流程|工作过程|实际怎么做|如何开展|步骤|交接|交付物|产物|异常|事理|森林|周期|返工|回滚|上线/i,
  risk: /风险|错误|审计|过时|缺陷|问题|重合|紊乱|缺口|健康/i,
  overview: /是什么|介绍|全貌|总体|核心|总览|全景|岗位理解/i,
  learning: /学习|课程|怎么学|路径|前置知识|培养|知识|技能/i,
};

export const TOOL_PURPOSES = CORE_TOOL_PURPOSES;

function coreCall(name: CoreRoleToolName, args: Record<string, unknown>): RoleToolCall {
  return { name, args };
}

/**
 * The main conversation Agent sees six orthogonal perception tools. Complex
 * build/iteration/workspace behavior is loaded as a Skill and launched as an
 * asynchronous job; it is deliberately absent from this short-path planner.
 */
export function planRoleTools(request: AgentRequest): RoleToolCall[] {
  const query = request.message.trim();
  const targetIds = request.references.map((reference) => reference.targetId);
  const calls: RoleToolCall[] = [];

  if (request.references.length) {
    calls.push(coreCall("read_role_objects", { targets: request.references }));
  }
  if (patterns.process.test(query)) {
    calls.push(coreCall("trace_work_process", {
      start: request.references[0],
      query,
      depth: 6,
    }));
  }
  if (patterns.graph.test(query) && request.references.length) {
    calls.push(coreCall("query_role_graph", {
      start: request.references[0],
      depth: 2,
      direction: "both",
    }));
  }
  if (patterns.evidence.test(query) && request.references.length) {
    calls.push(coreCall("inspect_role_evidence", { targets: request.references.slice(0, 8) }));
  }
  if (patterns.risk.test(query) || patterns.overview.test(query)) {
    calls.push(coreCall("audit_role_package", {
      profile: patterns.risk.test(query) ? "health" : "overview",
      targetIds,
    }));
  }

  const needsSearch = request.references.length === 0
    || patterns.learning.test(query)
    || (!patterns.process.test(query) && !patterns.evidence.test(query) && calls.length < 2);
  if (needsSearch) {
    calls.push(coreCall("search_role_knowledge", { query, topK: 10, selectedIds: targetIds }));
  }
  if (!calls.length) calls.push(coreCall("audit_role_package", { profile: "overview" }));

  const unique = new Map<string, RoleToolCall>();
  for (const call of calls) {
    if (!CORE_ROLE_TOOL_NAMES.includes(call.name as CoreRoleToolName)) continue;
    const args = Object.fromEntries(Object.entries(call.args).filter(([, value]) => value !== undefined));
    const key = `${call.name}:${JSON.stringify(args)}`;
    if (!unique.has(key)) unique.set(key, { name: call.name, args });
  }
  return [...unique.values()].slice(0, 4);
}
