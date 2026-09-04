import type { RoleToolErrorCode } from "./types";

const errorPolicy: Record<RoleToolErrorCode, { retryable: boolean; whoFixes: "system" | "agent" | "user" | "developer" }> = {
  INVALID_REFERENCE: { retryable: false, whoFixes: "agent" },
  SNAPSHOT_MISMATCH: { retryable: false, whoFixes: "user" },
  PACKAGE_NOT_PUBLISHABLE: { retryable: false, whoFixes: "developer" },
  HASH_MISMATCH: { retryable: false, whoFixes: "developer" },
  OBJECT_NOT_FOUND: { retryable: false, whoFixes: "agent" },
  AMBIGUOUS_ALIAS: { retryable: false, whoFixes: "agent" },
  RESULT_LIMIT_EXCEEDED: { retryable: false, whoFixes: "agent" },
  GRAPH_CYCLE_DETECTED: { retryable: false, whoFixes: "developer" },
  EVIDENCE_UNAVAILABLE: { retryable: false, whoFixes: "agent" },
  TEMPORAL_POLICY_BLOCKED: { retryable: false, whoFixes: "user" },
  DUPLICATE_CALL: { retryable: false, whoFixes: "agent" },
  TOOL_TIMEOUT: { retryable: true, whoFixes: "system" },
  CANCELLED: { retryable: false, whoFixes: "user" },
  INTERNAL_ERROR: { retryable: true, whoFixes: "developer" },
};

export class RoleToolError extends Error {
  readonly code: RoleToolErrorCode;
  readonly retryable: boolean;
  readonly whoFixes: "system" | "agent" | "user" | "developer";
  readonly suggestedAction?: string;

  constructor(code: RoleToolErrorCode, message: string, suggestedAction?: string) {
    super(message);
    this.name = "RoleToolError";
    this.code = code;
    this.retryable = errorPolicy[code].retryable;
    this.whoFixes = errorPolicy[code].whoFixes;
    this.suggestedAction = suggestedAction;
  }
}
