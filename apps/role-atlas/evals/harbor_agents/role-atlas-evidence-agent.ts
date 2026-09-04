import { createHash } from "node:crypto";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createRoleAgent } from "@/lib/agent/graph";
import type { AgentEvent, AgentRequest } from "@/lib/agent/events";
import { createModelInvoker, type ModelInvoker } from "@/lib/agent/model";
import { SnapshotRoleRuntime } from "@/lib/agent/snapshot-runtime";
import type { ColdStartBuildResult } from "@/lib/build/types";
import type { NodeReference, RoleToolCall } from "@/lib/role-package/types";

type HarborMessage = { role?: string; type?: string; content?: unknown };
type HarborGraphInput = { messages?: HarborMessage[] };
type HarborInvokeConfig = { configurable?: { thread_id?: unknown } };

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(moduleDir, "../..");
const packageRoot = path.join(projectRoot, "packages/golden/llm-app-engineer/1.0.0");
const logRoot = process.env.ROLE_ATLAS_LOG_DIR || "/logs/agent";
const eventLogPath = path.join(logRoot, "role-atlas-events.jsonl");
const runLogPath = path.join(logRoot, "role-atlas-run.json");
const expectedRootHash = "206e01b0285eb9b7c3ff5e432bbd2ccbc2561f61ba954e730339b249ca084a76";

const reference: NodeReference = {
  packageId: "role-package:llm-app-engineer-golden",
  packageVersion: "1.0.0",
  snapshotId: "snapshot:role:llm-app-engineer@2026-08-24-gold-v1",
  targetId: "knowledge:llmapp:peft-lora-conditional",
};

function messageText(message: HarborMessage | undefined) {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    return message.content.map((item) => typeof item === "string" ? item : JSON.stringify(item)).join("\n");
  }
  return message.content == null ? "" : String(message.content);
}

async function jsonFile<T>(filename: string): Promise<T> {
  return JSON.parse(await readFile(path.join(packageRoot, filename), "utf8")) as T;
}

async function loadGoldenSnapshot(): Promise<ColdStartBuildResult> {
  const snapshot = await jsonFile<Record<string, unknown>>("snapshot.json");
  const validationReport = await jsonFile<{ audit: ColdStartBuildResult["audit"] }>("validation-report.json");
  return {
    ...snapshot,
    sources: await jsonFile<ColdStartBuildResult["sources"]>("sources.json"),
    semantic: await jsonFile<ColdStartBuildResult["semantic"]>("semantic-graph.json"),
    process: await jsonFile<ColdStartBuildResult["process"]>("work-process-forest.json"),
    audit: validationReport.audit,
  } as ColdStartBuildResult;
}

async function packageIntegrity() {
  const manifest = await jsonFile<{ rootHash: string; hashes: Record<string, string> }>("manifest.json");
  const components = await Promise.all(Object.entries(manifest.hashes).map(async ([filename, expected]) => {
    const content = await readFile(path.join(packageRoot, filename));
    const actual = createHash("sha256").update(content).digest("hex");
    return { filename, expected, actual, valid: expected === actual };
  }));
  return {
    rootHash: manifest.rootHash,
    rootHashValid: manifest.rootHash === expectedRootHash,
    components,
    valid: manifest.rootHash === expectedRootHash && components.every((item) => item.valid),
  };
}

async function sourceManifest() {
  const manifestPath = path.join(projectRoot, "role-atlas-source-manifest.json");
  return JSON.parse(await readFile(manifestPath, "utf8")) as Record<string, unknown>;
}

export const roleAtlasHarborGraph = {
  async invoke(input: HarborGraphInput, config: HarborInvokeConfig = {}) {
    await mkdir(logRoot, { recursive: true });
    await writeFile(eventLogPath, "");
    let writeQueue = Promise.resolve();
    let recordSeq = 0;
    const record = (recordType: string, payload: unknown) => {
      const item = {
        schemaVersion: "1.0",
        seq: recordSeq += 1,
        time: new Date().toISOString(),
        recordType,
        payload,
      };
      writeQueue = writeQueue.then(() => appendFile(eventLogPath, `${JSON.stringify(item)}\n`));
      return writeQueue;
    };

    const instruction = messageText(input.messages?.[input.messages.length - 1]).trim();
    if (!instruction) throw new Error("Harbor instruction is empty");
    const apiKey = process.env.MIMO_API_KEY?.trim();
    if (!apiKey) throw new Error("MIMO_API_KEY is required for the approved Harness");

    const sessionId = String(config.configurable?.thread_id || process.env.HARBOR_SESSION_ID || "harbor-role-atlas");
    const runId = `harbor:${sessionId}`.slice(0, 180);
    const before = await packageIntegrity();
    if (!before.valid) throw new Error("Frozen golden package failed its pre-run integrity check");
    const harnessSource = await sourceManifest();
    await record("run.config", {
      runId,
      sessionId,
      provider: "mimo",
      model: "mimo-v2.5",
      thinking: true,
      packageRootHash: before.rootHash,
      reference,
      harnessSource,
    });

    const baseModel = createModelInvoker({ provider: "mimo", model: "mimo-v2.5", apiKey, thinking: true });
    const model: ModelInvoker = async function* (modelInput) {
      await record("model.request", {
        system: modelInput.system,
        user: modelInput.user,
        thinking: modelInput.thinking,
        maxCompletionTokens: modelInput.maxCompletionTokens,
        timeoutMs: modelInput.timeoutMs,
        totalTimeoutMs: modelInput.totalTimeoutMs,
      });
      for await (const part of baseModel(modelInput)) {
        await record("model.delta", part);
        yield part;
      }
      await record("model.completed", {});
    };

    const snapshot = await loadGoldenSnapshot();
    const rawRuntime = new SnapshotRoleRuntime(snapshot);
    const runtime = {
      get descriptor() { return rawRuntime.descriptor; },
      validateReferences: rawRuntime.validateReferences.bind(rawRuntime),
      execute: async (call: RoleToolCall, executingRunId: string) => {
        await record("tool.call", { call, runId: executingRunId });
        const result = await rawRuntime.execute(call, executingRunId);
        await record("tool.result", { call, runId: executingRunId, result });
        return result;
      },
    } as unknown as SnapshotRoleRuntime;

    const request: AgentRequest = {
      runId,
      sessionId,
      message: instruction,
      history: [],
      references: [reference],
    };

    let answer = "";
    let terminationReason = "completed";
    try {
      const graph = createRoleAgent(model, runtime);
      const stream = await graph.stream(
        { request },
        { configurable: { thread_id: sessionId }, streamMode: "custom" },
      );
      for await (const item of stream) {
        const event = item as AgentEvent;
        await record("role_agent.event", event);
        if (event.kind === "answer.completed" && typeof event.payload.answer === "string") {
          answer = event.payload.answer;
        }
      }
      if (!answer.trim()) throw new Error("Role Atlas Agent returned an empty answer");
    } catch (error) {
      terminationReason = "error";
      await record("run.error", {
        name: error instanceof Error ? error.name : "Error",
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    } finally {
      const after = await packageIntegrity();
      await record("run.integrity", { before, after, unchanged: JSON.stringify(before) === JSON.stringify(after) });
      await record("run.terminated", { reason: terminationReason });
      await writeQueue;
    }

    const after = await packageIntegrity();
    const runSummary = {
      schemaVersion: "1.0",
      runId,
      sessionId,
      terminationReason,
      answer,
      packageIntegrity: after,
      harnessSource,
      reference,
    };
    await writeFile(runLogPath, `${JSON.stringify(runSummary, null, 2)}\n`);
    return {
      messages: [
        ...(input.messages || []),
        { type: "ai", role: "assistant", content: answer },
      ],
      roleAtlas: runSummary,
    };
  },
};
