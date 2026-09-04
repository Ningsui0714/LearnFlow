import { z } from "zod/v4";
import { createModelInvoker, type ModelInvoker } from "@/lib/agent/model";
import { getConversation, saveProjectCandidateFromSnapshotRisk } from "@/lib/projects/repository";
import { createRiskResearchRepairSkill } from "@/lib/risk/graph";
import { riskRunRequestSchema, type RiskEvent, type RiskRunResult } from "@/lib/risk/types";
import { resolveProviderConfig, resolveSearchProviderConfig } from "@/lib/server-runtime-config";
import {
  appendSnapshotRiskEvent,
  completeSnapshotRiskRun,
  failSnapshotRiskRun,
  getLatestSnapshotRiskRun,
  saveSnapshotRiskCheckpoint,
  startSnapshotRiskRun,
} from "@/lib/snapshots/repository";
import { resolveSnapshot } from "@/lib/snapshots/resolver";
import { workerRuntimeBindings } from "@/lib/worker-runtime-bindings";

export const runtime = "edge";

const postSchema = z.object({
  risk: riskRunRequestSchema,
  conversationId: z.string().min(4).max(100).optional(),
  providerConfig: z.unknown().optional(),
  searchConfig: z.unknown().optional(),
});

function failureEvent(input: { runId: string; snapshotRef: { snapshotId: string }; projectId?: string }, error: unknown): RiskEvent {
  const raw = error instanceof Error ? error.message : "未知错误";
  const message = /401|api key|authentication|auth/i.test(raw)
    ? "模型或检索供应商拒绝了凭据。"
    : /429|rate limit/i.test(raw)
      ? "供应商正在限流，运行已保存，可稍后重试。"
      : /abort/i.test(raw)
        ? "风险研究已取消，当前快照未改变。"
        : `风险研究失败：${raw}`;
  return {
    version: "1.0",
    runId: input.runId,
    snapshotId: input.snapshotRef.snapshotId,
    projectId: input.projectId,
    seq: Number.MAX_SAFE_INTEGER,
    time: new Date().toISOString(),
    kind: "risk.run.failed",
    phase: "system",
    payload: { message, retryable: !/凭据/.test(message) },
  };
}

export async function GET(request: Request) {
  const snapshotId = new URL(request.url).searchParams.get("snapshotId");
  if (!snapshotId) return Response.json({ error: "缺少 snapshotId。" }, { status: 400 });
  try {
    return Response.json({ run: await getLatestSnapshotRiskRun(snapshotId) });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "风险运行读取失败。" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  let parsed: z.infer<typeof postSchema>;
  try {
    parsed = postSchema.parse(await request.json());
  } catch (error) {
    return Response.json({ error: "风险研究范围或运行配置无效。", detail: error instanceof Error ? error.message : undefined }, { status: 400 });
  }

  const resolved = await resolveSnapshot(parsed.risk.snapshotRef).catch(() => null);
  if (!resolved) return Response.json({ error: "没有可审计的岗位快照。" }, { status: 404 });
  if (parsed.conversationId) {
    const conversation = await getConversation(parsed.conversationId).catch(() => null);
    if (!conversation || !resolved.reference.projectId || conversation.conversation.projectId !== resolved.reference.projectId) {
      return Response.json({ error: "研究会话不存在或不属于当前项目。" }, { status: 404 });
    }
  }

  let model: ModelInvoker;
  let searchConfig;
  try {
    const bindings = workerRuntimeBindings();
    const needsResearch = parsed.risk.webResearch && !["scan", "verify"].includes(parsed.risk.mode);
    model = needsResearch
      ? createModelInvoker(resolveProviderConfig(parsed.providerConfig, bindings))
      : async function* unusedModel() {
        yield* [];
        throw new Error("当前运行没有进入模型重建阶段。");
      };
    searchConfig = needsResearch ? resolveSearchProviderConfig(parsed.searchConfig, bindings) : undefined;
  } catch (error) {
    const message = error instanceof Error && error.message === "SERVER_MODEL_NOT_CONFIGURED"
      ? "服务端尚未配置模型 API Key。"
      : error instanceof Error && error.message === "SERVER_SEARCH_NOT_CONFIGURED"
        ? "已开启定向研究，但尚未配置搜索 API Key。"
        : "模型或搜索配置无效。";
    return Response.json({ error: message }, { status: 400 });
  }

  const riskRequest = {
    ...parsed.risk,
    snapshotRef: resolved.reference,
    projectId: resolved.reference.projectId,
    baseVersionId: resolved.version.id,
  };
  try {
    await startSnapshotRiskRun(riskRequest);
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "无法创建风险研究运行。" }, { status: 500 });
  }

  const graph = createRiskResearchRepairSkill({
    model,
    searchConfig,
    onCheckpoint: (phase, state) => saveSnapshotRiskCheckpoint(riskRequest.runId, phase, state),
  });
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      void (async () => {
        let persistence = Promise.resolve();
        const queueEvent = (event: RiskEvent) => {
          persistence = persistence.then(() => appendSnapshotRiskEvent(event));
        };
        try {
          const events = await graph.stream(
            {
              request: riskRequest,
              baseVersionId: resolved.version.id,
              base: resolved.result,
              candidate: resolved.result,
              iteration: 1,
              researchPlans: [],
              researchReports: [],
              researchedSources: [],
              patches: [],
              migrations: {},
              improved: false,
            },
            {
              configurable: { thread_id: `${riskRequest.snapshotRef.snapshotId}:${riskRequest.runId}` },
              streamMode: "custom",
              signal: request.signal,
            },
          );
          for await (const raw of events) {
            const event = raw as RiskEvent;
            if (event.kind === "risk.run.completed" && event.payload.result) {
              await persistence;
              const result = event.payload.result as RiskRunResult;
              const candidateSnapshotId = await completeSnapshotRiskRun(result);
              const projectVersionId = resolved.reference.projectId && result.improved
                ? await saveProjectCandidateFromSnapshotRisk(result, resolved.reference.projectId, parsed.conversationId)
                : null;
              if (candidateSnapshotId) {
                const versionEvent: RiskEvent = {
                  ...event,
                  kind: "risk.version.created",
                  phase: "version",
                  payload: { candidateSnapshotId, projectVersionId, snapshotId: result.candidate.snapshot.id, status: "candidate" },
                };
                const completedEvent: RiskEvent = { ...event, seq: event.seq + 1, payload: { ...event.payload, candidateSnapshotId, projectVersionId } };
                await appendSnapshotRiskEvent(versionEvent);
                await appendSnapshotRiskEvent(completedEvent);
                controller.enqueue(encoder.encode(`${JSON.stringify(versionEvent)}\n`));
                controller.enqueue(encoder.encode(`${JSON.stringify(completedEvent)}\n`));
              } else {
                await appendSnapshotRiskEvent(event);
                controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
              }
              continue;
            }
            queueEvent(event);
            controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
          }
        } catch (error) {
          const event = failureEvent(riskRequest, error);
          await persistence.catch(() => undefined);
          await Promise.allSettled([
            appendSnapshotRiskEvent(event),
            failSnapshotRiskRun(riskRequest.runId, String(event.payload.message || "风险研究失败"), request.signal.aborted),
          ]);
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        } finally {
          await persistence.catch(() => undefined);
          controller.close();
        }
      })();
    },
  });
  return new Response(stream, {
    headers: {
      "content-type": "application/x-ndjson; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}
