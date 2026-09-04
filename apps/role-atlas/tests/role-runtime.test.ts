import assert from "node:assert/strict";
import test from "node:test";
import { createNodeReference, rolePackageRuntime } from "@/lib/role-package/runtime";
import type { RoleToolCall, RoleToolName } from "@/lib/role-package/types";

const run = (call: RoleToolCall, runId = crypto.randomUUID()) => rolePackageRuntime.execute(call, runId);

test("岗位包在启动时固定到已验证、可发布的静态快照", async () => {
  const result = await run({ name: "get_role_package_status", args: {} });
  assert.equal(result.ok, true);
  assert.equal((result.data as { packageVersion: string }).packageVersion, "1.1.0");
  assert.equal((result.data as { snapshotAsOf: string }).snapshotAsOf, "2026-08-19");
  assert.equal((result.data as { publishable: boolean }).publishable, true);
  assert.equal((result.data as { compositeSnapshotVersion: string }).compositeSnapshotVersion, "1.2.0");
  assert.equal((result.data as { workProcess: { packageVersion: string } }).workProcess.packageVersion, "0.1.0");
});

test("精确节点读取支持版本化引用、字段裁剪和批量部分成功", async () => {
  const reference = createNodeReference("task:T-02");
  const exact = await run({ name: "read_role_objects", args: { targets: [reference], fields: ["title", "deliverables"] } });
  assert.equal(exact.ok, true);
  assert.equal(exact.coverage.returned, 1);
  assert.equal(exact.citations[0].targetId, "task:T-02");

  const partial = await run({ name: "read_role_objects", args: { targets: [reference, "missing:node"] } });
  assert.equal(partial.ok, true);
  assert.equal(partial.coverage.partial, true);
  assert.equal((partial.data as { missing: string[] }).missing[0], "missing:node");
});

test("过期节点引用被稳定拒绝，不静默读取其他快照", async () => {
  const stale = { ...createNodeReference("task:T-02"), packageVersion: "0.9.0" };
  const result = await run({ name: "read_role_objects", args: { targets: [stale] } });
  assert.equal(result.ok, false);
  assert.equal(result.error?.code, "SNAPSHOT_MISMATCH");
  assert.equal(result.error?.whoFixes, "user");
});

test("同一运行内的重复调用被去重并返回相同内容", async () => {
  const runId = crypto.randomUUID();
  const call: RoleToolCall = { name: "search_role_knowledge", args: { query: "RAG 评测与调优", topK: 5 } };
  const first = await run(call, runId);
  const second = await run(call, runId);
  assert.equal(first.diagnostics.deduplicated, false);
  assert.equal(second.diagnostics.deduplicated, true);
  assert.deepEqual(first.data, second.data);
  assert.ok(second.warnings.some((warning) => warning.code === "DUPLICATE_CALL"));
});

test("搜索与图查询在零结果和深度上限下保持可解释覆盖", async () => {
  const zero = await run({ name: "search_role_knowledge", args: { query: "不存在的量子香蕉术语xyzqv", topK: 4 } });
  assert.equal(zero.ok, true);
  assert.ok(zero.warnings.some((warning) => warning.code === "ZERO_RESULTS"));

  const graph = await run({ name: "query_role_graph", args: { start: "task:T-02", depth: 99, direction: "both" } });
  assert.equal(graph.ok, true);
  assert.equal((graph.data as { depth: number }).depth, 2);
  assert.ok(graph.coverage.returned > 0);
});

test("十五类语义与事理工具都返回统一信封且不会泄露运行状态", async () => {
  const calls: RoleToolCall[] = [
    { name: "get_role_overview", args: {} },
    { name: "get_role_package_status", args: {} },
    { name: "read_role_objects", args: { targets: ["task:T-02"] } },
    { name: "resolve_role_targets", args: { query: "RAG 调优" } },
    { name: "search_role_knowledge", args: { query: "RAG", topK: 5 } },
    { name: "query_role_graph", args: { start: "task:T-02", depth: 1 } },
    { name: "trace_role_paths", args: { start: "task:T-02", targetTypes: ["knowledge_skill"], maxDepth: 4 } },
    { name: "read_task_bundle", args: { task: "task:T-03" } },
    { name: "project_role_view", args: { viewId: "learning-path", focusId: "task:T-02" } },
    { name: "compare_role_objects", args: { targets: ["task:T-02", "task:T-03"] } },
    { name: "inspect_role_evidence", args: { target: "task:T-02", mode: "trace" } },
    { name: "read_work_scenarios", args: { scenarioIds: ["scenario:SC-01"] } },
    { name: "trace_work_process", args: { start: "scenario:SC-02", depth: 8 } },
    { name: "inspect_role_process_alignment", args: { statuses: ["partial", "gap"] } },
    { name: "audit_role_package", args: { profile: "semantic" } },
  ];
  const results = await Promise.all(calls.map((call) => run(call)));
  assert.deepEqual(results.map((result) => result.tool), calls.map((call) => call.name as RoleToolName));
  for (const result of results) {
    assert.equal(result.ok, true, `${result.tool}: ${result.error?.message || "unexpected failure"}`);
    assert.equal(typeof result.context, "string");
    assert.equal(typeof result.coverage.complete, "boolean");
    assert.equal(result.diagnostics.packageVersion, "1.1.0");
  }
});

test("任务包同时返回语义关系和候选工作事件，过程引用固定到伴随包", async () => {
  const bundle = await run({ name: "read_task_bundle", args: { task: "task:T-03" } });
  assert.equal(bundle.ok, true);
  const data = bundle.data as { scenarios: unknown[]; workEvents: unknown[]; processAlignment: { status: string } };
  assert.ok(data.scenarios.length > 0);
  assert.ok(data.workEvents.length > 0);
  assert.notEqual(data.processAlignment.status, "gap");

  const processReference = createNodeReference("event:SC-01:04");
  assert.equal(processReference.packageId, "work-process-package:llm-app-engineer");
  const exactProcess = await run({ name: "read_role_objects", args: { targets: [processReference], fields: ["label", "summary"] } });
  assert.equal(exactProcess.ok, true);
  assert.equal(exactProcess.citations[0].artifactKind, "work_process");
  const process = await run({ name: "trace_work_process", args: { start: processReference, depth: 3 } });
  assert.equal(process.ok, true);
  assert.ok(process.citations.some((citation) => citation.artifactKind === "work_process" && citation.knowledgeState === "inferred_pattern"));
});

test("任务—过程对齐把未覆盖任务转成可研究缺口", async () => {
  const result = await run({ name: "inspect_role_process_alignment", args: { target: "task:T-05" } });
  assert.equal(result.ok, true);
  const data = result.data as { records: Array<{ status: string }>; researchPriorities: Array<{ targetId: string }> };
  assert.equal(data.records[0].status, "gap");
  assert.ok(data.researchPriorities.some((item) => item.targetId === "task:T-05"));
});

test("结果上限和未知对象通过机器可处理错误返回", async () => {
  const oversized = await run({ name: "read_role_objects", args: { targets: Array.from({ length: 26 }, (_, index) => `node:${index}`) } });
  assert.equal(oversized.ok, false);
  assert.equal(oversized.error?.code, "RESULT_LIMIT_EXCEEDED");

  const unknown = await run({ name: "query_role_graph", args: { start: "missing:node" } });
  assert.equal(unknown.ok, false);
  assert.equal(unknown.error?.code, "OBJECT_NOT_FOUND");
});
