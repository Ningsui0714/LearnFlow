import { z } from "zod/v4";
import type { ColdStartBuildResult } from "@/lib/build/types";

/**
 * A stable, storage-neutral pointer to one immutable role snapshot.
 * Project/version fields are routing hints, never part of the domain identity.
 */
export const snapshotReferenceSchema = z.object({
  snapshotId: z.string().min(4).max(240),
  packageVersion: z.string().min(1).max(80).optional(),
  projectId: z.string().min(4).max(100).optional(),
  versionId: z.string().min(4).max(220).optional(),
});

export type SnapshotReference = z.infer<typeof snapshotReferenceSchema>;

export type ResolvedSnapshot = {
  reference: SnapshotReference;
  title: string;
  description: string;
  market: string;
  version: {
    id: string;
    version: string;
    status: string;
    snapshotId: string;
  };
  result: ColdStartBuildResult;
  source: "bundled" | "project" | "snapshot-store" | "registry";
};
