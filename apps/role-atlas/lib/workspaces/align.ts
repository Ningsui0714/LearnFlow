import type { ColdStartBuildResult, SemanticNode } from "@/lib/build/types";
import type {
  WorkspaceAlignmentReport,
  WorkspaceIngestionResult,
  WorkspaceObservation,
  WorkspaceTaskAlignment,
} from "./types";

const stopTokens = new Set([
  "工作", "任务", "岗位", "系统", "进行", "相关", "工程师", "负责", "实现", "处理", "支持", "需要",
  "the", "and", "for", "with", "from", "into", "this", "that", "work", "task", "system",
]);

function tokens(value: string) {
  const lowered = value.toLowerCase();
  const ascii = lowered.match(/[a-z][a-z0-9_.+#/-]{1,}/gu) || [];
  const chineseRuns = lowered.match(/[\p{Script=Han}]{2,}/gu) || [];
  const chinese = chineseRuns.flatMap((run) => {
    const chars = [...run];
    return [run, ...chars.map((char) => char), ...chars.slice(0, -1).map((char, index) => `${char}${chars[index + 1]}`)];
  });
  return new Set([...ascii, ...chinese].filter((token) => token.length > 1 && !stopTokens.has(token)));
}

function overlapScore(observation: WorkspaceObservation, task: SemanticNode) {
  const observationTokens = tokens(`${observation.title}\n${observation.summary}\n${observation.source.content.slice(0, 16_000)}`);
  const labelTokens = tokens([task.label, ...task.aliases].join(" "));
  const detailTokens = tokens(task.summary);
  const labelMatches = [...labelTokens].filter((token) => observationTokens.has(token)).length;
  const detailMatches = [...detailTokens].filter((token) => observationTokens.has(token)).length;
  const labelCoverage = labelTokens.size ? labelMatches / labelTokens.size : 0;
  const detailCoverage = detailTokens.size ? detailMatches / detailTokens.size : 0;
  const evidenceDensity = Math.min(1, (labelMatches * 2 + detailMatches) / 8);
  return Math.min(1, labelCoverage * 0.58 + detailCoverage * 0.24 + evidenceDensity * 0.18);
}

export function alignWorkspaceToSnapshot(
  ingestion: WorkspaceIngestionResult,
  base: ColdStartBuildResult,
  threshold = 0.26,
): WorkspaceAlignmentReport {
  const tasks = base.semantic.nodes.filter((node) => node.type === "task" && node.lifecycle !== "rejected");
  const alignments: WorkspaceTaskAlignment[] = ingestion.observations.map((observation) => {
    const ranked = tasks
      .map((task) => ({ task, score: overlapScore(observation, task) }))
      .sort((a, b) => b.score - a.score);
    const best = ranked[0];
    if (!best || best.score < threshold) return {
      observationId: observation.id,
      episodeId: observation.episodeId,
      score: best?.score || 0,
      status: "candidate_task",
      evidenceResourceIds: observation.resourceIds,
    };
    return {
      observationId: observation.id,
      episodeId: observation.episodeId,
      taskId: best.task.id,
      taskLabel: best.task.label,
      score: best.score,
      status: "aligned",
      evidenceResourceIds: observation.resourceIds,
    };
  });
  const coveredTaskIds = new Set(alignments.flatMap((alignment) => alignment.taskId ? [alignment.taskId] : []));
  return {
    snapshotId: base.snapshot.id,
    alignedCount: alignments.filter((alignment) => alignment.status === "aligned").length,
    candidateTaskCount: alignments.filter((alignment) => alignment.status === "candidate_task").length,
    uncoveredTaskIds: tasks.filter((task) => !coveredTaskIds.has(task.id)).map((task) => task.id),
    alignments,
  };
}
