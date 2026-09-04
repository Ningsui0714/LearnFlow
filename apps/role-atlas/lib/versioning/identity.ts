import type { ColdStartBuildResult } from "@/lib/build/types";

type IdentityObject = { id: string; label: string; type: string; aliases: string[] };

function normalize(value: string) {
  return value.normalize("NFKC").toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
}

function terms(item: IdentityObject) {
  return new Set([item.label, ...item.aliases].filter(Boolean).map(normalize));
}

function score(left: IdentityObject, right: IdentityObject) {
  if (left.type !== right.type) return 0;
  const leftTerms = terms(left);
  const rightTerms = terms(right);
  if ([...leftTerms].some((term) => rightTerms.has(term))) return 1;
  const a = normalize(left.label);
  const b = normalize(right.label);
  if (!a || !b) return 0;
  if (a.includes(b) || b.includes(a)) return 0.88;
  const pairs = (value: string) => new Set(Array.from({ length: Math.max(0, value.length - 1) }, (_, index) => value.slice(index, index + 2)));
  const aPairs = pairs(a);
  const bPairs = pairs(b);
  const shared = [...aPairs].filter((pair) => bPairs.has(pair)).length;
  return aPairs.size + bPairs.size ? 2 * shared / (aPairs.size + bPairs.size) : 0;
}

function identityObjects(result: ColdStartBuildResult): IdentityObject[] {
  return [
    ...result.semantic.nodes.map((item) => ({ id: item.id, label: item.label, type: `semantic:${item.type}`, aliases: item.aliases || [] })),
    ...result.process.scenarios.map((item) => ({ id: item.id, label: item.label, type: "process:scenario", aliases: [] })),
    ...result.process.nodes.map((item) => ({ id: item.id, label: item.label, type: `process:${item.kind}`, aliases: [] })),
  ];
}

function replaceIds(value: unknown, replacements: Map<string, string>): unknown {
  if (typeof value === "string") return replacements.get(value) || value;
  if (Array.isArray(value)) return value.map((item) => replaceIds(item, replacements));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, replaceIds(item, replacements)]));
  }
  return value;
}

/** Preserve parent IDs only for unambiguous, same-dimension concepts. */
export function preserveStableIdentities(base: ColdStartBuildResult, candidate: ColdStartBuildResult) {
  const previous = identityObjects(base);
  const next = identityObjects(candidate);
  const previousIds = new Set(previous.map((item) => item.id));
  const claimed = new Set<string>();
  const replacements = new Map<string, string>();
  for (const item of next) {
    if (previousIds.has(item.id)) { claimed.add(item.id); continue; }
    const matches = previous
      .filter((other) => !claimed.has(other.id))
      .map((other) => ({ other, score: score(other, item) }))
      .filter((match) => match.score >= 0.93)
      .sort((left, right) => right.score - left.score);
    if (matches.length !== 1) continue;
    replacements.set(item.id, matches[0].other.id);
    claimed.add(matches[0].other.id);
  }
  if (replacements.size === 0) return { result: structuredClone(candidate), replacements };
  return { result: replaceIds(structuredClone(candidate), replacements) as ColdStartBuildResult, replacements };
}
