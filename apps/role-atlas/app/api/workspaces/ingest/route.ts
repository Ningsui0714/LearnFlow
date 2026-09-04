import { z } from "zod/v4";
import { snapshotReferenceSchema } from "@/lib/snapshots/types";
import { resolveSnapshot } from "@/lib/snapshots/resolver";
import { createWorkspaceIngestionSkill } from "@/lib/workspaces/graph";
import {
  appendWorkspaceEvent,
  completeWorkspaceIngestion,
  failWorkspaceIngestion,
  getLatestWorkspaceIngestion,
  saveWorkspaceCheckpoint,
  startWorkspaceIngestion,
} from "@/lib/workspaces/repository";
import { workspaceIngestionRequestSchema, type WorkspaceAlignmentReport, type WorkspaceIngestionResult } from "@/lib/workspaces/types";
import type { WorkspaceRunEvent } from "@/lib/workspaces/events";

export const runtime = "edge";

const postSchema = z.object({
  workspace: workspaceIngestionRequestSchema,
  snapshotRef: snapshotReferenceSchema.optional(),
});

export async function GET(request: Request) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("projectId") || undefined;
  const snapshotId = url.searchParams.get("snapshotId") || undefined;
  if (!projectId && !snapshotId) return Response.json({ error: "缺少 projectId 或 snapshotId。" }, { status: 400 });
  try {
    return Response.json({ run: await getLatestWorkspaceIngestion({ projectId, snapshotId }) });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "工作区运行读取失败。" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  let parsed: z.infer<typeof postSchema>;
  try {
    parsed = postSchema.parse(await request.json());
  } catch (error) {
    return Response.json({ error: "真实工作区连接或扫描范围无效。", detail: error instanceof Error ? error.message : undefined }, { status: 400 });
  }
  const resolved = parsed.snapshotRef ? await resolveSnapshot(parsed.snapshotRef).catch(() => null) : null;
  if (parsed.snapshotRef && !resolved) return Response.json({ error: "没有可对齐的岗位快照。" }, { status: 404 });
  const workspaceRequest = {
    ...parsed.workspace,
    projectId: resolved?.reference.projectId || parsed.workspace.projectId,
  };
  await startWorkspaceIngestion({ request: workspaceRequest, baseSnapshotId: resolved?.reference.snapshotId });
  const graph = createWorkspaceIngestionSkill({
    onCheckpoint: (phase, state) => saveWorkspaceCheckpoint(workspaceRequest.runId, phase, state),
  });
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      void (async () => {
        let result: WorkspaceIngestionResult | undefined;
        let alignment: WorkspaceAlignmentReport | undefined;
        let persistence = Promise.resolve();
        const queueEvent = (event: WorkspaceRunEvent) => {
          persistence = persistence.then(() => appendWorkspaceEvent(event));
        };
        try {
          const events = await graph.stream({
            request: workspaceRequest,
            base: resolved?.result,
            observationLanes: [],
            observations: [],
            safetyFindings: [],
            quarantinedResourceIds: [],
          }, {
            configurable: { thread_id: `${workspaceRequest.runId}:workspace` },
            streamMode: "custom",
            signal: request.signal,
          });
          for await (const raw of events) {
            const event = raw as WorkspaceRunEvent;
            queueEvent(event);
            if (event.kind === "workspace.run.completed") {
              result = event.payload.result;
              alignment = event.payload.alignment;
            }
            controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
          }
          await persistence;
          if (!result) throw new Error("工作区编排没有产生扫描结果。");
          await completeWorkspaceIngestion({ runId: workspaceRequest.runId, result, alignment });
        } catch (error) {
          await persistence.catch(() => undefined);
          const message = error instanceof Error ? error.message : "工作区扫描失败。";
          const event: WorkspaceRunEvent = {
            version: "1.0",
            runId: workspaceRequest.runId,
            projectId: workspaceRequest.projectId,
            seq: Number.MAX_SAFE_INTEGER,
            time: new Date().toISOString(),
            kind: "workspace.run.failed",
            phase: "system",
            payload: { message },
          };
          await Promise.allSettled([
            appendWorkspaceEvent(event),
            failWorkspaceIngestion(workspaceRequest.runId, message, request.signal.aborted),
          ]);
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        } finally {
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
