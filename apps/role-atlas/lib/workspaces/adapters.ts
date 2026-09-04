import { z } from "zod/v4";
import { stableHash } from "@/lib/build/compiler";
import type {
  WorkspaceAdapterId,
  WorkspaceConnection,
  WorkspaceEvidenceClass,
  WorkspaceEvent,
  WorkspaceLink,
  WorkspaceObject,
  WorkspacePackage,
  WorkspaceResource,
} from "./types";
import { workspaceConnectionSchema, workspacePackageSchema } from "./types";

type Adapter = {
  id: WorkspaceAdapterId;
  normalize(connection: WorkspaceConnection): WorkspacePackage;
};

function packageId(connection: WorkspaceConnection, seed: string) {
  return connection.packageId || `workspace:${connection.adapterId}:${stableHash(seed)}`;
}

function provenance(connection: WorkspaceConnection, fallback?: { locator?: string; publisher?: string; license?: string; sourceUpdatedAt?: string }) {
  return {
    locator: connection.provenance.locator || fallback?.locator,
    publisher: connection.provenance.publisher || fallback?.publisher,
    license: connection.provenance.license || fallback?.license,
    capturedAt: connection.provenance.capturedAt || new Date().toISOString(),
    sourceUpdatedAt: fallback?.sourceUpdatedAt,
    notes: [],
  };
}

function evidenceClass(connection: WorkspaceConnection, fallback: WorkspaceEvidenceClass) {
  return connection.evidenceClass || fallback;
}

function resource(input: Omit<WorkspaceResource, "metadata"> & { metadata?: Record<string, unknown> }): WorkspaceResource {
  return { ...input, metadata: input.metadata || {} };
}

function event(input: Omit<WorkspaceEvent, "objectIds" | "resourceIds" | "summary"> & {
  summary?: string;
  objectIds?: string[];
  resourceIds?: string[];
}): WorkspaceEvent {
  return { ...input, summary: input.summary || "", objectIds: input.objectIds || [], resourceIds: input.resourceIds || [] };
}

const githubTraceSchema = z.object({
  repository: z.object({
    fullName: z.string().min(3).max(240),
    url: z.string().url().max(700),
    license: z.string().max(120).optional(),
    baseCommit: z.string().max(120).optional(),
  }),
  issue: z.object({
    number: z.number().int().positive(),
    title: z.string().min(1).max(400),
    body: z.string().max(60_000).default(""),
    url: z.string().url().max(700).optional(),
    createdAt: z.string().max(80).optional(),
    closedAt: z.string().max(80).optional(),
  }),
  pullRequest: z.object({
    number: z.number().int().positive(),
    title: z.string().min(1).max(400),
    body: z.string().max(60_000).default(""),
    url: z.string().url().max(700).optional(),
    createdAt: z.string().max(80).optional(),
    mergedAt: z.string().max(80).optional(),
    baseSha: z.string().max(120).optional(),
    headSha: z.string().max(120).optional(),
  }),
  commits: z.array(z.object({ sha: z.string().min(4).max(120), message: z.string().max(2_000), at: z.string().max(80).optional() })).max(100).default([]),
  reviews: z.array(z.object({ id: z.string().max(120), state: z.string().max(80), body: z.string().max(20_000).default(""), at: z.string().max(80).optional() })).max(100).default([]),
  checks: z.array(z.object({ id: z.string().max(120), name: z.string().max(240), status: z.string().max(80), conclusion: z.string().max(80).optional(), at: z.string().max(80).optional() })).max(200).default([]),
  files: z.array(z.object({ path: z.string().min(1).max(500), patch: z.string().max(80_000).optional(), additions: z.number().int().min(0).optional(), deletions: z.number().int().min(0).optional() })).max(200).default([]),
  release: z.object({ tag: z.string().max(120), url: z.string().url().max(700).optional(), publishedAt: z.string().max(80).optional() }).optional(),
});

const githubAdapter: Adapter = {
  id: "github_trace",
  normalize(connection) {
    const data = githubTraceSchema.parse(connection.payload);
    const caseId = `github:${data.repository.fullName}:issue:${data.issue.number}`;
    const id = packageId(connection, `${data.repository.fullName}:${data.issue.number}:${data.pullRequest.number}`);
    const repoObjectId = `${id}:repo`;
    const issueObjectId = `${id}:work-item`;
    const resources: WorkspaceResource[] = [
      resource({ id: `${id}:issue`, kind: "task", title: `Issue #${data.issue.number} ${data.issue.title}`, summary: data.issue.body.slice(0, 8_000), content: data.issue.body, locator: data.issue.url, occurredAt: data.issue.createdAt, caseId }),
      resource({ id: `${id}:pr`, kind: "communication", title: `PR #${data.pullRequest.number} ${data.pullRequest.title}`, summary: data.pullRequest.body.slice(0, 8_000), content: data.pullRequest.body, locator: data.pullRequest.url, occurredAt: data.pullRequest.createdAt, caseId }),
      ...data.files.map((file, index) => resource({ id: `${id}:patch:${index + 1}`, kind: "patch", title: file.path, summary: `修改 ${file.path}，新增 ${file.additions || 0} 行，删除 ${file.deletions || 0} 行。`, content: file.patch, caseId, metadata: { path: file.path, additions: file.additions, deletions: file.deletions } })),
      ...data.reviews.map((review) => resource({ id: `${id}:review:${review.id}`, kind: "review", title: `代码审查 ${review.state}`, summary: review.body.slice(0, 8_000), content: review.body, occurredAt: review.at, actorRole: "reviewer", caseId, metadata: { state: review.state } })),
      ...data.checks.map((check) => resource({ id: `${id}:check:${check.id}`, kind: "ci_run", title: check.name, summary: `状态 ${check.status}${check.conclusion ? `，结论 ${check.conclusion}` : ""}`, occurredAt: check.at, actorRole: "automation", caseId, metadata: { status: check.status, conclusion: check.conclusion } })),
    ];
    if (data.release) resources.push(resource({ id: `${id}:release:${data.release.tag}`, kind: "release", title: `Release ${data.release.tag}`, summary: "该修改已进入公开发布版本。", locator: data.release.url, occurredAt: data.release.publishedAt, caseId }));
    const events: WorkspaceEvent[] = [
      event({ id: `${id}:event:issue-opened`, caseId, type: "task_received", label: "问题被提出", summary: data.issue.title, occurredAt: data.issue.createdAt, sequence: 1, actorRole: "requester", objectIds: [issueObjectId], resourceIds: [`${id}:issue`] }),
      event({ id: `${id}:event:pr-opened`, caseId, type: "solution_proposed", label: "提交解决方案", summary: data.pullRequest.title, occurredAt: data.pullRequest.createdAt, sequence: 2, actorRole: "developer", objectIds: [issueObjectId, repoObjectId], resourceIds: [`${id}:pr`, ...data.files.map((_, index) => `${id}:patch:${index + 1}`)] }),
      ...data.commits.map((commit, index) => event({ id: `${id}:event:commit:${commit.sha}`, caseId, type: "work_performed", label: "提交代码变更", summary: commit.message, occurredAt: commit.at, sequence: 3 + index, actorRole: "developer", objectIds: [repoObjectId, issueObjectId] })),
      ...data.reviews.map((review, index) => event({ id: `${id}:event:review:${review.id}`, caseId, type: "quality_review", label: `代码审查 ${review.state}`, summary: review.body.slice(0, 2_000), occurredAt: review.at, sequence: 103 + index, actorRole: "reviewer", objectIds: [repoObjectId, issueObjectId], resourceIds: [`${id}:review:${review.id}`], status: review.state })),
      ...data.checks.map((check, index) => event({ id: `${id}:event:check:${check.id}`, caseId, type: "verification", label: check.name, summary: check.conclusion || check.status, occurredAt: check.at, sequence: 203 + index, actorRole: "automation", objectIds: [repoObjectId, issueObjectId], resourceIds: [`${id}:check:${check.id}`], status: check.conclusion || check.status })),
      event({ id: `${id}:event:merged`, caseId, type: "accepted", label: "变更合并", summary: `PR #${data.pullRequest.number} 已合并。`, occurredAt: data.pullRequest.mergedAt, sequence: 400, actorRole: "maintainer", objectIds: [repoObjectId, issueObjectId], resourceIds: [`${id}:pr`], outcome: "解决方案进入主分支" }),
    ];
    if (data.release) events.push(event({ id: `${id}:event:released`, caseId, type: "delivered", label: "进入发布版本", summary: data.release.tag, occurredAt: data.release.publishedAt, sequence: 500, actorRole: "release_manager", objectIds: [repoObjectId], resourceIds: [`${id}:release:${data.release.tag}`], outcome: `发布 ${data.release.tag}` }));
    const objects: WorkspaceObject[] = [
      { id: repoObjectId, type: "repository", label: data.repository.fullName, summary: "公开软件仓库", resourceIds: resources.map((item) => item.id), metadata: { baseCommit: data.repository.baseCommit } },
      { id: issueObjectId, type: "work_item", label: data.issue.title, summary: data.issue.body.slice(0, 2_000), resourceIds: [`${id}:issue`, `${id}:pr`], metadata: { issueNumber: data.issue.number, pullRequestNumber: data.pullRequest.number } },
    ];
    const links: WorkspaceLink[] = [{ id: `${id}:link:pr-resolves-issue`, type: "resolves", source: `${id}:pr`, target: issueObjectId, resourceIds: [`${id}:issue`, `${id}:pr`] }];
    return workspacePackageSchema.parse({
      protocolVersion: "1.0",
      id,
      title: connection.title || `${data.repository.fullName} Issue #${data.issue.number} 工作链`,
      adapterId: "github_trace",
      roleHint: connection.roleHint || "软件开发工程师",
      description: "由公开 Issue、PR、代码变更、审查、CI 与发布记录重建的真实开发工作 episode。",
      evidenceClass: evidenceClass(connection, "real_work_activity"),
      visibility: connection.visibility,
      provenance: provenance(connection, { locator: data.issue.url || data.repository.url, publisher: "GitHub", license: data.repository.license, sourceUpdatedAt: data.release?.publishedAt || data.pullRequest.mergedAt }),
      timeWindow: { start: data.issue.createdAt, end: data.release?.publishedAt || data.pullRequest.mergedAt, asOf: data.release?.publishedAt || data.pullRequest.mergedAt },
      resources,
      objects,
      events,
      links,
      metadata: { repository: data.repository.fullName, issueNumber: data.issue.number, pullRequestNumber: data.pullRequest.number },
    });
  },
};

const swebenchSchema = z.object({
  instanceId: z.string().min(1).max(180),
  repo: z.string().min(3).max(240),
  problemStatement: z.string().min(1).max(80_000),
  baseCommit: z.string().min(4).max(120),
  patch: z.string().max(100_000).default(""),
  testPatch: z.string().max(100_000).default(""),
  failToPass: z.array(z.string().max(500)).max(200).default([]),
  passToPass: z.array(z.string().max(500)).max(500).default([]),
  createdAt: z.string().max(80).optional(),
  version: z.string().max(80).optional(),
  url: z.string().url().max(700).optional(),
});

const swebenchAdapter: Adapter = {
  id: "swebench",
  normalize(connection) {
    const data = swebenchSchema.parse(connection.payload);
    const id = packageId(connection, data.instanceId);
    const caseId = `swebench:${data.instanceId}`;
    const workItemId = `${id}:case`;
    const resources: WorkspaceResource[] = [
      resource({ id: `${id}:problem`, kind: "task", title: data.instanceId, summary: data.problemStatement.slice(0, 8_000), content: data.problemStatement, locator: data.url, occurredAt: data.createdAt, caseId }),
      resource({ id: `${id}:base`, kind: "code_snapshot", title: `${data.repo}@${data.baseCommit}`, summary: "问题修复前的代码库状态。", caseId, metadata: { repo: data.repo, baseCommit: data.baseCommit } }),
      resource({ id: `${id}:patch`, kind: "patch", title: "人工解决 Patch", summary: "对应真实合并 PR 的解决方案。", content: data.patch, caseId }),
      resource({ id: `${id}:tests`, kind: "test", title: "回归测试与验收", summary: `FAIL_TO_PASS ${data.failToPass.length} 项；PASS_TO_PASS ${data.passToPass.length} 项。`, content: [data.testPatch, `FAIL_TO_PASS\n${data.failToPass.join("\n")}`, `PASS_TO_PASS\n${data.passToPass.join("\n")}`].filter(Boolean).join("\n\n"), caseId }),
      resource({ id: `${id}:outcome`, kind: "outcome", title: "人工修复通过验证", summary: "Patch 使目标失败测试转为通过，并保持既有通过测试。", caseId }),
    ];
    return workspacePackageSchema.parse({
      protocolVersion: "1.0",
      id,
      title: connection.title || `SWE-bench ${data.instanceId}`,
      adapterId: "swebench",
      roleHint: connection.roleHint || "软件开发工程师",
      description: "由真实 GitHub Issue、修复前代码、人工 Patch 与可执行测试构成的精选工作案例。",
      evidenceClass: evidenceClass(connection, "curated_real_case"),
      visibility: connection.visibility,
      provenance: provenance(connection, { locator: data.url || "https://github.com/SWE-bench/SWE-bench", publisher: "SWE-bench", license: "MIT / underlying repository licenses" }),
      timeWindow: { start: data.createdAt, end: data.createdAt, asOf: data.createdAt },
      resources,
      objects: [
        { id: workItemId, type: "dataset_case", label: data.instanceId, summary: data.problemStatement.slice(0, 2_000), resourceIds: resources.map((item) => item.id), metadata: { repo: data.repo, baseCommit: data.baseCommit, version: data.version } },
      ],
      events: [
        event({ id: `${id}:event:received`, caseId, type: "task_received", label: "接收真实软件问题", summary: data.problemStatement.slice(0, 2_000), occurredAt: data.createdAt, sequence: 1, actorRole: "developer", objectIds: [workItemId], resourceIds: [`${id}:problem`, `${id}:base`] }),
        event({ id: `${id}:event:changed`, caseId, type: "work_performed", label: "修改代码解决问题", summary: "人工 PR 对代码库实施修改。", sequence: 2, actorRole: "developer", objectIds: [workItemId], resourceIds: [`${id}:patch`] }),
        event({ id: `${id}:event:verified`, caseId, type: "verification", label: "执行回归测试", summary: `${data.failToPass.length} 项目标测试由失败转为通过。`, sequence: 3, actorRole: "test_automation", objectIds: [workItemId], resourceIds: [`${id}:tests`], status: "passed", outcome: "问题通过可执行测试验证" }),
      ],
      links: [],
      metadata: { instanceId: data.instanceId, repo: data.repo },
    });
  },
};

const devgptSchema = z.object({
  conversationId: z.string().min(1).max(180),
  title: z.string().max(400).optional(),
  source: z.object({ kind: z.string().max(80), url: z.string().url().max(700).optional(), repository: z.string().max(240).optional() }),
  turns: z.array(z.object({ prompt: z.string().min(1).max(60_000), answer: z.string().max(80_000).default(""), at: z.string().max(80).optional() })).min(1).max(80),
  codeSnippets: z.array(z.string().max(80_000)).max(80).default([]),
  linkedArtifact: z.object({ title: z.string().max(400), body: z.string().max(60_000).default(""), url: z.string().url().max(700).optional(), outcome: z.string().max(2_000).optional() }).optional(),
});

const devgptAdapter: Adapter = {
  id: "devgpt",
  normalize(connection) {
    const data = devgptSchema.parse(connection.payload);
    const id = packageId(connection, data.conversationId);
    const caseId = `devgpt:${data.conversationId}`;
    const resources: WorkspaceResource[] = [
      ...(data.linkedArtifact ? [resource({ id: `${id}:task`, kind: "task", title: data.linkedArtifact.title, summary: data.linkedArtifact.body.slice(0, 8_000), content: data.linkedArtifact.body, locator: data.linkedArtifact.url, caseId })] : []),
      ...data.turns.map((turn, index) => resource({ id: `${id}:conversation:${index + 1}`, kind: "communication", title: `AI 协作轮次 ${index + 1}`, summary: turn.prompt.slice(0, 4_000), content: `开发者：${turn.prompt}\n\nAI：${turn.answer}`, occurredAt: turn.at, actorRole: "developer_and_ai", caseId })),
      ...data.codeSnippets.map((snippet, index) => resource({ id: `${id}:code:${index + 1}`, kind: "patch", title: `对话关联代码片段 ${index + 1}`, summary: "开发对话中产生或讨论的代码。", content: snippet, caseId })),
      ...(data.linkedArtifact?.outcome ? [resource({ id: `${id}:outcome`, kind: "outcome", title: "关联开发产物结果", summary: data.linkedArtifact.outcome, caseId })] : []),
    ];
    const objectId = `${id}:work-item`;
    return workspacePackageSchema.parse({
      protocolVersion: "1.0",
      id,
      title: connection.title || data.title || `DevGPT ${data.conversationId}`,
      adapterId: "devgpt",
      roleHint: connection.roleHint || "大模型应用工程师",
      description: "开发者与 AI 对话及其关联软件开发产物形成的真实 AI 辅助工作 episode。",
      evidenceClass: evidenceClass(connection, "real_work_activity"),
      visibility: connection.visibility,
      provenance: provenance(connection, { locator: data.source.url || data.linkedArtifact?.url || "https://zenodo.org/records/8436454", publisher: "DevGPT", license: "CC-BY-4.0" }),
      timeWindow: { start: data.turns[0]?.at, end: data.turns.at(-1)?.at, asOf: data.turns.at(-1)?.at },
      resources,
      objects: [{ id: objectId, type: "work_item", label: data.linkedArtifact?.title || data.title || "AI 辅助开发任务", summary: data.linkedArtifact?.body.slice(0, 2_000) || "", resourceIds: resources.map((item) => item.id), metadata: { sourceKind: data.source.kind, repository: data.source.repository } }],
      events: data.turns.map((turn, index) => event({ id: `${id}:event:turn:${index + 1}`, caseId, type: index === 0 ? "task_clarification" : "solution_iteration", label: index === 0 ? "向 AI 表达开发问题" : "继续迭代解决方案", summary: turn.prompt.slice(0, 2_000), occurredAt: turn.at, sequence: index + 1, actorRole: "developer_and_ai", objectIds: [objectId], resourceIds: [`${id}:conversation:${index + 1}`, ...(data.codeSnippets[index] ? [`${id}:code:${index + 1}`] : [])], outcome: index === data.turns.length - 1 ? data.linkedArtifact?.outcome : undefined })),
      links: [],
      metadata: { conversationId: data.conversationId, sourceKind: data.source.kind },
    });
  },
};

const bugBenchmarkSchema = z.object({
  caseId: z.string().min(1).max(180),
  project: z.string().min(1).max(240),
  language: z.string().max(80),
  bugDescription: z.string().max(60_000).default(""),
  buggyRevision: z.string().min(1).max(160),
  fixedRevision: z.string().min(1).max(160),
  patch: z.string().max(100_000).default(""),
  triggeringTests: z.array(z.string().max(1_000)).max(200).default([]),
  stackTrace: z.string().max(60_000).optional(),
  url: z.string().url().max(700).optional(),
  benchmark: z.string().max(120).default("bug-benchmark"),
});

const bugBenchmarkAdapter: Adapter = {
  id: "bug_benchmark",
  normalize(connection) {
    const data = bugBenchmarkSchema.parse(connection.payload);
    const id = packageId(connection, `${data.benchmark}:${data.caseId}`);
    const caseId = `bug:${data.benchmark}:${data.caseId}`;
    const resources: WorkspaceResource[] = [
      resource({ id: `${id}:bug`, kind: "incident", title: `${data.project} ${data.caseId}`, summary: data.bugDescription, content: data.stackTrace ? `${data.bugDescription}\n\n${data.stackTrace}` : data.bugDescription, locator: data.url, caseId }),
      resource({ id: `${id}:buggy`, kind: "code_snapshot", title: `错误版本 ${data.buggyRevision}`, summary: `${data.project} 的可复现错误版本。`, caseId }),
      resource({ id: `${id}:fix`, kind: "patch", title: `修复版本 ${data.fixedRevision}`, summary: "开发者实施的真实修复。", content: data.patch, caseId }),
      resource({ id: `${id}:tests`, kind: "test", title: "触发与回归测试", summary: `${data.triggeringTests.length} 项触发测试。`, content: data.triggeringTests.join("\n"), caseId }),
    ];
    const objectId = `${id}:bug-case`;
    return workspacePackageSchema.parse({
      protocolVersion: "1.0",
      id,
      title: connection.title || `${data.benchmark} ${data.caseId}`,
      adapterId: "bug_benchmark",
      roleHint: connection.roleHint || "软件测试工程师",
      description: "由真实项目版本历史提取并隔离、可复现的缺陷修复案例。",
      evidenceClass: evidenceClass(connection, "curated_real_case"),
      visibility: connection.visibility,
      provenance: provenance(connection, { locator: data.url, publisher: data.benchmark }),
      timeWindow: {},
      resources,
      objects: [{ id: objectId, type: "dataset_case", label: `${data.project} ${data.caseId}`, summary: data.bugDescription, resourceIds: resources.map((item) => item.id), metadata: { project: data.project, language: data.language } }],
      events: [
        event({ id: `${id}:event:reproduce`, caseId, type: "failure_reproduced", label: "检出错误版本并复现缺陷", sequence: 1, actorRole: "test_engineer", objectIds: [objectId], resourceIds: [`${id}:bug`, `${id}:buggy`, `${id}:tests`] }),
        event({ id: `${id}:event:fix`, caseId, type: "work_performed", label: "实施缺陷修复", sequence: 2, actorRole: "developer", objectIds: [objectId], resourceIds: [`${id}:fix`] }),
        event({ id: `${id}:event:verify`, caseId, type: "verification", label: "执行回归验证", sequence: 3, actorRole: "test_engineer", objectIds: [objectId], resourceIds: [`${id}:tests`], status: "passed", outcome: "触发测试在修复版本通过" }),
      ],
      links: [],
      metadata: { benchmark: data.benchmark, project: data.project, language: data.language },
    });
  },
};

const eventLogSchema = z.object({
  datasetId: z.string().min(1).max(180),
  title: z.string().min(1).max(240),
  description: z.string().max(8_000).default(""),
  events: z.array(z.object({
    id: z.string().min(1).max(180),
    caseId: z.string().min(1).max(180),
    activity: z.string().min(1).max(240),
    timestamp: z.string().max(80).optional(),
    actorRole: z.string().max(120).optional(),
    status: z.string().max(80).optional(),
    objectIds: z.array(z.string().max(180)).max(40).default([]),
    detail: z.string().max(8_000).default(""),
  })).min(1).max(5_000),
  objects: z.array(z.object({ id: z.string().min(1).max(180), type: z.string().max(120), label: z.string().max(240) })).max(500).default([]),
  locator: z.string().url().max(700).optional(),
  publisher: z.string().max(240).optional(),
  license: z.string().max(120).optional(),
});

function normalizeEventLog(connection: WorkspaceConnection, adapterId: "event_log" | "soc_case") {
  const data = eventLogSchema.parse(connection.payload);
  const id = packageId(connection, data.datasetId);
  const resources: WorkspaceResource[] = data.events.map((item) => resource({
    id: `${id}:resource:${item.id}`,
    kind: adapterId === "soc_case" ? "incident" : "event_log",
    title: item.activity,
    summary: item.detail,
    content: item.detail || undefined,
    occurredAt: item.timestamp,
    actorRole: item.actorRole,
    caseId: item.caseId,
    metadata: { status: item.status },
  }));
  const objects: WorkspaceObject[] = data.objects.map((item) => ({
    id: `${id}:object:${item.id}`,
    type: adapterId === "soc_case" ? "incident" : "work_item",
    label: item.label,
    summary: item.type,
    resourceIds: [],
    metadata: { sourceType: item.type },
  }));
  const objectIds = new Set(objects.map((item) => item.id));
  const events = data.events.map((item, index) => event({
    id: `${id}:event:${item.id}`,
    caseId: item.caseId,
    type: item.status === "closed" ? "case_closed" : "work_event",
    label: item.activity,
    summary: item.detail,
    occurredAt: item.timestamp,
    sequence: index + 1,
    actorRole: item.actorRole,
    objectIds: item.objectIds.map((objectId) => `${id}:object:${objectId}`).filter((objectId) => objectIds.has(objectId)),
    resourceIds: [`${id}:resource:${item.id}`],
    status: item.status,
    outcome: item.status === "closed" ? "案例关闭" : undefined,
  }));
  return workspacePackageSchema.parse({
    protocolVersion: "1.0",
    id,
    title: connection.title || data.title,
    adapterId,
    roleHint: connection.roleHint || (adapterId === "soc_case" ? "网络安全运营工程师" : "IT 运维工程师"),
    description: data.description,
    evidenceClass: evidenceClass(connection, adapterId === "soc_case" ? "teaching_simulation" : "production_trace"),
    visibility: connection.visibility,
    provenance: provenance(connection, { locator: data.locator, publisher: data.publisher, license: data.license }),
    timeWindow: { start: data.events[0]?.timestamp, end: data.events.at(-1)?.timestamp, asOf: data.events.at(-1)?.timestamp },
    resources,
    objects,
    events,
    links: [],
    metadata: { datasetId: data.datasetId },
  });
}

const eventLogAdapter: Adapter = { id: "event_log", normalize: (connection) => normalizeEventLog(connection, "event_log") };
const socAdapter: Adapter = { id: "soc_case", normalize: (connection) => normalizeEventLog(connection, "soc_case") };

const telemetrySchema = z.object({
  caseId: z.string().min(1).max(180),
  system: z.string().min(1).max(240),
  faultType: z.string().max(160),
  rootCause: z.string().max(2_000).default(""),
  symptoms: z.array(z.string().max(1_000)).max(100).default([]),
  metrics: z.array(z.object({ name: z.string().max(240), summary: z.string().max(2_000), at: z.string().max(80).optional() })).max(200).default([]),
  logs: z.array(z.object({ id: z.string().max(120), text: z.string().max(20_000), at: z.string().max(80).optional(), service: z.string().max(160).optional() })).max(500).default([]),
  traces: z.array(z.object({ id: z.string().max(120), summary: z.string().max(4_000), at: z.string().max(80).optional(), service: z.string().max(160).optional() })).max(500).default([]),
  actions: z.array(z.object({ label: z.string().max(240), detail: z.string().max(4_000).default(""), at: z.string().max(80).optional(), outcome: z.string().max(2_000).optional() })).max(100).default([]),
  startedAt: z.string().max(80).optional(),
  endedAt: z.string().max(80).optional(),
  locator: z.string().url().max(700).optional(),
  dataset: z.string().max(160).optional(),
});

const telemetryAdapter: Adapter = {
  id: "telemetry_case",
  normalize(connection) {
    const data = telemetrySchema.parse(connection.payload);
    const id = packageId(connection, `${data.dataset || "telemetry"}:${data.caseId}`);
    const caseId = `telemetry:${data.caseId}`;
    const incidentId = `${id}:incident`;
    const resources: WorkspaceResource[] = [
      resource({ id: `${id}:incident`, kind: "incident", title: `${data.system} ${data.faultType}`, summary: data.symptoms.join("；"), content: `症状：${data.symptoms.join("；")}\n根因：${data.rootCause}`, locator: data.locator, occurredAt: data.startedAt, caseId }),
      ...data.metrics.map((item, index) => resource({ id: `${id}:metric:${index + 1}`, kind: "metric", title: item.name, summary: item.summary, occurredAt: item.at, caseId })),
      ...data.logs.map((item) => resource({ id: `${id}:log:${item.id}`, kind: "log", title: item.service ? `${item.service} 日志` : "运行日志", summary: item.text.slice(0, 4_000), content: item.text, occurredAt: item.at, caseId, metadata: { service: item.service } })),
      ...data.traces.map((item) => resource({ id: `${id}:trace:${item.id}`, kind: "trace", title: item.service ? `${item.service} Trace` : "调用链", summary: item.summary, occurredAt: item.at, caseId, metadata: { service: item.service } })),
      resource({ id: `${id}:outcome`, kind: "outcome", title: "已标注根因", summary: data.rootCause || "数据集未提供根因文本。", occurredAt: data.endedAt, caseId }),
    ];
    const events: WorkspaceEvent[] = [
      event({ id: `${id}:event:detected`, caseId, type: "incident_detected", label: "检测到运行异常", summary: data.symptoms.join("；"), occurredAt: data.startedAt, sequence: 1, actorRole: "sre", objectIds: [incidentId], resourceIds: [`${id}:incident`, ...data.metrics.map((_, index) => `${id}:metric:${index + 1}`)] }),
      event({ id: `${id}:event:correlated`, caseId, type: "evidence_correlated", label: "关联指标、日志和调用链", summary: `日志 ${data.logs.length} 条；Trace ${data.traces.length} 条。`, sequence: 2, actorRole: "sre", objectIds: [incidentId], resourceIds: [...data.logs.map((item) => `${id}:log:${item.id}`), ...data.traces.map((item) => `${id}:trace:${item.id}`)] }),
      ...data.actions.map((item, index) => event({ id: `${id}:event:action:${index + 1}`, caseId, type: "mitigation", label: item.label, summary: item.detail, occurredAt: item.at, sequence: 3 + index, actorRole: "sre", objectIds: [incidentId], outcome: item.outcome })),
      event({ id: `${id}:event:resolved`, caseId, type: "root_cause_confirmed", label: "确认根因并完成验证", summary: data.rootCause, occurredAt: data.endedAt, sequence: 500, actorRole: "sre", objectIds: [incidentId], resourceIds: [`${id}:outcome`], status: "resolved", outcome: data.rootCause }),
    ];
    return workspacePackageSchema.parse({
      protocolVersion: "1.0",
      id,
      title: connection.title || `${data.dataset || "遥测数据"} ${data.caseId}`,
      adapterId: "telemetry_case",
      roleHint: connection.roleHint || "SRE/运维开发工程师",
      description: "由指标、日志、Trace、故障动作与根因标注形成的可复现运维工作案例。",
      evidenceClass: evidenceClass(connection, "controlled_experiment"),
      visibility: connection.visibility,
      provenance: provenance(connection, { locator: data.locator, publisher: data.dataset }),
      timeWindow: { start: data.startedAt, end: data.endedAt, asOf: data.endedAt },
      resources,
      objects: [{ id: incidentId, type: "incident", label: `${data.system} ${data.faultType}`, summary: data.symptoms.join("；"), resourceIds: resources.map((item) => item.id), metadata: { system: data.system, faultType: data.faultType, rootCause: data.rootCause } }],
      events,
      links: [],
      metadata: { dataset: data.dataset, system: data.system, faultType: data.faultType },
    });
  },
};

const genericAdapter: Adapter = {
  id: "generic_package",
  normalize(connection) {
    const parsed = workspacePackageSchema.parse(connection.payload);
    return workspacePackageSchema.parse({
      ...parsed,
      id: connection.packageId || parsed.id,
      title: connection.title || parsed.title,
      roleHint: connection.roleHint || parsed.roleHint,
      visibility: connection.visibility || parsed.visibility,
      evidenceClass: connection.evidenceClass || parsed.evidenceClass,
      provenance: {
        ...parsed.provenance,
        ...Object.fromEntries(Object.entries(connection.provenance).filter(([, value]) => Boolean(value))),
        capturedAt: connection.provenance.capturedAt || parsed.provenance.capturedAt,
      },
    });
  },
};

const registry = new Map<WorkspaceAdapterId, Adapter>([
  [genericAdapter.id, genericAdapter],
  [githubAdapter.id, githubAdapter],
  [devgptAdapter.id, devgptAdapter],
  [swebenchAdapter.id, swebenchAdapter],
  [bugBenchmarkAdapter.id, bugBenchmarkAdapter],
  [eventLogAdapter.id, eventLogAdapter],
  [telemetryAdapter.id, telemetryAdapter],
  [socAdapter.id, socAdapter],
]);

export function normalizeWorkspaceConnection(input: unknown) {
  const connection = workspaceConnectionSchema.parse(input);
  const adapter = registry.get(connection.adapterId);
  if (!adapter) throw new Error(`WORKSPACE_ADAPTER_NOT_FOUND:${connection.adapterId}`);
  return adapter.normalize(connection);
}

export function workspaceAdapterIds() {
  return [...registry.keys()];
}
