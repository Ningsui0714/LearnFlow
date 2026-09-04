import type { ColdStartBuildResult } from "@/lib/build/types";
import { canonicalStringify, sha256Hex } from "./canonical";

/** Snapshot-domain fingerprint excludes release metadata and redacted display text. */
export async function snapshotDomainHash(result: ColdStartBuildResult) {
  return sha256Hex(canonicalStringify({
    brief: result.brief,
    snapshot: result.snapshot,
    semantic: result.semantic,
    process: result.process,
    audit: result.audit,
    sources: {
      assets: result.sources.assets.map((asset) => ({ id: asset.id, kind: asset.kind, contentHash: asset.contentHash, observedAt: asset.observedAt, publishedAt: asset.publishedAt })),
      segments: result.sources.segments.map((segment) => ({ id: segment.id, sourceId: segment.sourceId, contentHash: segment.contentHash, ordinal: segment.ordinal })),
      evidenceBindings: result.sources.evidenceBindings,
    },
  }));
}
