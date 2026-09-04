import { stableHash } from "@/lib/build/compiler";
import type { SourceInput } from "@/lib/build/types";
import type {
  WorkspaceEvidenceClass,
  WorkspaceIngestionRequest,
  WorkspaceIngestionResult,
  WorkspaceInventory,
  WorkspaceObservation,
  WorkspacePackage,
  WorkspaceResource,
  WorkspaceSafetyFinding,
} from "./types";

const secretPatterns = [
  /\b(?:ghp|github_pat|sk|xai|tvly)-[A-Za-z0-9_-]{16,}\b/gu,
  /\bAKIA[0-9A-Z]{16}\b/gu,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b/giu,
  /\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*["']?[^\s"']{10,}["']?/giu,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/gu,
];

const emailPattern = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/giu;
const phonePattern = /(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)/gu;
const localPathPatterns = [
  /\/(?:Users|home|var\/folders)\/[^\s"'<>]+/gu,
  /\b[A-Z]:\\(?:Users|Documents and Settings)\\[^\s"'<>]+/giu,
];

function finding(input: Omit<WorkspaceSafetyFinding, "id">): WorkspaceSafetyFinding {
  return { ...input, id: `workspace-finding:${stableHash(JSON.stringify(input))}` };
}

function replaceMatches(value: string, patterns: RegExp[], replacement: string) {
  let count = 0;
  let output = value;
  for (const pattern of patterns) {
    output = output.replace(pattern, () => {
      count += 1;
      return replacement;
    });
  }
  return { value: output, count };
}

function sanitizeText(value: string, redactPersonalData: boolean) {
  const secretResult = replaceMatches(value, secretPatterns, "[REDACTED_SECRET]");
  const pathResult = replaceMatches(secretResult.value, localPathPatterns, "[REDACTED_LOCAL_PATH]");
  const emailResult = redactPersonalData
    ? replaceMatches(pathResult.value, [emailPattern], "[REDACTED_EMAIL]")
    : { value: pathResult.value, count: 0 };
  const phoneResult = redactPersonalData
    ? replaceMatches(emailResult.value, [phonePattern], "[REDACTED_PHONE]")
    : { value: emailResult.value, count: 0 };
  return {
    value: phoneResult.value,
    secretCount: secretResult.count,
    pathCount: pathResult.count,
    personalCount: emailResult.count + phoneResult.count,
  };
}

export function sanitizeWorkspacePackage(input: WorkspacePackage, redactPersonalData = true) {
  const safetyFindings: WorkspaceSafetyFinding[] = [];
  const quarantinedResourceIds: string[] = [];
  const accepted: WorkspaceResource[] = [];
  const contentHashes = new Map<string, string>();

  for (const resource of input.resources) {
    const originalText = [resource.title, resource.summary, resource.content].filter(Boolean).join("\n").trim();
    if (!originalText) {
      quarantinedResourceIds.push(resource.id);
      safetyFindings.push(finding({
        severity: "warning",
        code: "EMPTY_RESOURCE",
        title: "空资源未进入岗位证据",
        resourceIds: [resource.id],
        action: "quarantined",
      }));
      continue;
    }

    const title = sanitizeText(resource.title, redactPersonalData);
    const summary = sanitizeText(resource.summary, redactPersonalData);
    const content = resource.content ? sanitizeText(resource.content, redactPersonalData) : undefined;
    const secretCount = title.secretCount + summary.secretCount + (content?.secretCount || 0);
    const pathCount = title.pathCount + summary.pathCount + (content?.pathCount || 0);
    const personalCount = title.personalCount + summary.personalCount + (content?.personalCount || 0);

    if (secretCount) safetyFindings.push(finding({
      severity: "error",
      code: "SECRET_LIKE_CONTENT",
      title: `已遮蔽 ${secretCount} 处疑似密钥或凭据`,
      resourceIds: [resource.id],
      action: "redacted",
    }));
    if (pathCount) safetyFindings.push(finding({
      severity: "warning",
      code: "LOCAL_PATH",
      title: `已遮蔽 ${pathCount} 处本机路径`,
      resourceIds: [resource.id],
      action: "redacted",
    }));
    if (personalCount) safetyFindings.push(finding({
      severity: "info",
      code: "PERSONAL_DATA_REDACTED",
      title: `已遮蔽 ${personalCount} 处个人联系方式`,
      resourceIds: [resource.id],
      action: "redacted",
    }));

    const sanitized = {
      ...resource,
      title: title.value,
      summary: summary.value,
      content: content?.value,
    };
    // Same conclusion text can legitimately belong to different CI checks or
    // deliverables. Only collapse resources whose type, title and payload all
    // match; otherwise keep both as independent work evidence.
    const normalizedContent = [sanitized.kind, sanitized.title, sanitized.summary, sanitized.content].filter(Boolean).join("\n").trim();
    const hash = stableHash(normalizedContent);
    const duplicateOf = contentHashes.get(hash);
    if (duplicateOf) {
      quarantinedResourceIds.push(resource.id);
      safetyFindings.push(finding({
        severity: "info",
        code: "DUPLICATE_RESOURCE",
        title: `与 ${duplicateOf} 内容重复，保留首份`,
        resourceIds: [resource.id, duplicateOf],
        action: "deduplicated",
      }));
      continue;
    }
    contentHashes.set(hash, resource.id);
    accepted.push(sanitized);
  }

  const acceptedIds = new Set(accepted.map((resource) => resource.id));
  const sanitizedPackage: WorkspacePackage = {
    ...input,
    resources: accepted,
    objects: input.objects.map((object) => ({
      ...object,
      resourceIds: object.resourceIds.filter((id) => acceptedIds.has(id)),
    })),
    events: input.events.map((event) => ({
      ...event,
      resourceIds: event.resourceIds.filter((id) => acceptedIds.has(id)),
    })),
    links: input.links.map((link) => ({
      ...link,
      resourceIds: link.resourceIds.filter((id) => acceptedIds.has(id)),
    })),
  };

  return { package: sanitizedPackage, safetyFindings, quarantinedResourceIds };
}

export function inspectWorkspaceInventory(input: WorkspacePackage, quarantinedResourceCount = 0): WorkspaceInventory {
  const kinds: WorkspaceInventory["kinds"] = {};
  for (const resource of input.resources) kinds[resource.kind] = (kinds[resource.kind] || 0) + 1;
  return {
    resourceCount: input.resources.length + quarantinedResourceCount,
    acceptedResourceCount: input.resources.length,
    quarantinedResourceCount,
    eventCount: input.events.length,
    objectCount: input.objects.length,
    caseCount: new Set(input.events.map((event) => event.caseId)).size,
    kinds,
  };
}

function evidenceTier(evidenceClass: WorkspaceEvidenceClass): SourceInput["sourceTier"] {
  if (evidenceClass === "real_work_activity" || evidenceClass === "production_trace") return "primary";
  if (evidenceClass === "curated_real_case" || evidenceClass === "controlled_experiment") return "secondary";
  return "contextual";
}

function publicLocator(input: WorkspacePackage) {
  if (input.visibility !== "publishable_metadata") return undefined;
  return input.provenance.locator?.slice(0, 500);
}

function observationSource(input: {
  package: WorkspacePackage;
  id: string;
  episodeId?: string;
  title: string;
  content: string;
  resourceIds: string[];
  observedAt?: string;
}): SourceInput {
  const locator = publicLocator(input.package);
  return {
    title: input.title.slice(0, 240),
    content: input.content.slice(0, 60_000),
    kind: "workspace_observation",
    locator,
    observedAt: input.observedAt || input.package.timeWindow.asOf || input.package.provenance.capturedAt,
    publisher: input.package.provenance.publisher,
    sourceTier: evidenceTier(input.package.evidenceClass),
    extractionMethod: "direct_fetch",
    workspaceEvidence: {
      workspacePackageId: input.package.id,
      adapterId: input.package.adapterId,
      resourceIds: input.resourceIds.slice(0, 40),
      episodeId: input.episodeId,
      evidenceClass: input.package.evidenceClass,
      license: input.package.provenance.license,
      publicLocator: locator,
      observedFrom: input.id,
    },
  };
}

function eventSort(a: WorkspacePackage["events"][number], b: WorkspacePackage["events"][number]) {
  if (a.sequence !== undefined || b.sequence !== undefined) return (a.sequence ?? Number.MAX_SAFE_INTEGER) - (b.sequence ?? Number.MAX_SAFE_INTEGER);
  return (a.occurredAt || "").localeCompare(b.occurredAt || "");
}

export function extractEpisodeObservations(input: WorkspacePackage): WorkspaceObservation[] {
  const byCase = new Map<string, WorkspacePackage["events"]>();
  for (const event of input.events) byCase.set(event.caseId, [...(byCase.get(event.caseId) || []), event]);
  const resourceMap = new Map(input.resources.map((resource) => [resource.id, resource]));
  return [...byCase.entries()].map(([caseId, rawEvents]) => {
    const events = [...rawEvents].sort(eventSort);
    const resourceIds = [...new Set(events.flatMap((event) => event.resourceIds))];
    const resources = resourceIds.map((id) => resourceMap.get(id)).filter((item): item is WorkspaceResource => Boolean(item));
    const outcome = [...events].reverse().find((event) => event.outcome)?.outcome;
    const summary = [events[0]?.label, events.at(-1)?.label, outcome].filter(Boolean).join(" → ");
    const timeline = events.map((event, index) => [
      `${index + 1}. ${event.occurredAt ? `[${event.occurredAt}] ` : ""}${event.label}`,
      event.actorRole ? `角色：${event.actorRole}` : "",
      event.summary,
      event.status ? `状态：${event.status}` : "",
      event.outcome ? `结果：${event.outcome}` : "",
    ].filter(Boolean).join("；")).join("\n");
    const artifacts = resources.map((resource) => [
      `- [${resource.kind}] ${resource.title}`,
      resource.summary,
      resource.content ? `内容摘录：${resource.content.slice(0, 6_000)}` : "",
    ].filter(Boolean).join("\n  ")).join("\n");
    const title = `工作 episode：${input.title} / ${caseId}`;
    const content = [
      `真实性等级：${input.evidenceClass}`,
      `适配器：${input.adapterId}`,
      `岗位提示：${input.roleHint || "未指定"}`,
      `事件链：\n${timeline}`,
      artifacts ? `关联交付物与证据：\n${artifacts}` : "",
      outcome ? `可观察结果：${outcome}` : "",
      "说明：这是工作实例证据，不应直接外推为所有组织的通用岗位职责。",
    ].filter(Boolean).join("\n\n");
    const id = `workspace-observation:${stableHash(`${input.id}:${caseId}`)}`;
    const observedAt = [...events].reverse().find((event) => event.occurredAt)?.occurredAt;
    return {
      id,
      episodeId: caseId,
      title,
      summary: summary || `${events.length} 个工作事件构成的实例链。`,
      resourceIds,
      eventIds: events.map((event) => event.id),
      source: observationSource({ package: input, id, episodeId: caseId, title, content, resourceIds, observedAt }),
    };
  });
}

export function extractArtifactObservations(input: WorkspacePackage): WorkspaceObservation[] {
  const eventResourceIds = new Set(input.events.flatMap((event) => event.resourceIds));
  return input.resources
    .filter((resource) => !eventResourceIds.has(resource.id))
    .map((resource) => {
      const title = `工作产物：${resource.title}`;
      const content = [
        `真实性等级：${input.evidenceClass}`,
        `资源类型：${resource.kind}`,
        `岗位提示：${input.roleHint || "未指定"}`,
        resource.summary,
        resource.content,
        "说明：这是独立工作产物证据；只有与任务或事理事件对齐后，才可用于实例化岗位快照。",
      ].filter(Boolean).join("\n\n");
      const id = `workspace-observation:${stableHash(`${input.id}:${resource.id}`)}`;
      return {
        id,
        episodeId: resource.caseId,
        title,
        summary: resource.summary || resource.title,
        resourceIds: [resource.id],
        eventIds: [],
        source: observationSource({
          package: input,
          id,
          episodeId: resource.caseId,
          title,
          content,
          resourceIds: [resource.id],
          observedAt: resource.occurredAt,
        }),
      };
    });
}

export function mergeWorkspaceObservations(lanes: WorkspaceObservation[], limit = 16) {
  const seen = new Set<string>();
  return lanes.filter((observation) => {
    const key = stableHash(observation.source.content);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).sort((a, b) => {
    if (Boolean(a.eventIds.length) !== Boolean(b.eventIds.length)) return b.eventIds.length - a.eventIds.length;
    return b.resourceIds.length - a.resourceIds.length;
  }).slice(0, limit);
}

export function ingestWorkspacePackage(request: WorkspaceIngestionRequest, normalized: WorkspacePackage): WorkspaceIngestionResult {
  const sanitized = sanitizeWorkspacePackage(normalized, request.redactPersonalData);
  const episodeObservations = extractEpisodeObservations(sanitized.package);
  const artifactObservations = extractArtifactObservations(sanitized.package);
  const observations = mergeWorkspaceObservations([...episodeObservations, ...artifactObservations], request.maxObservations);
  const warnings: string[] = [];
  if (!sanitized.package.events.length) warnings.push("没有可排序事件；本轮只能从独立资源提取工作产物观察。" );
  if (!observations.length) warnings.push("没有形成可进入岗位快照的工作观察，请补充任务、事件或工作产物。" );
  if (observations.length === request.maxObservations) warnings.push(`观察达到本轮上限 ${request.maxObservations}，其余材料仍保留在工作区包中。`);
  return {
    runId: request.runId,
    package: sanitized.package,
    inventory: inspectWorkspaceInventory(sanitized.package, sanitized.quarantinedResourceIds.length),
    safetyFindings: sanitized.safetyFindings,
    observations,
    quarantinedResourceIds: sanitized.quarantinedResourceIds,
    warnings,
  };
}
