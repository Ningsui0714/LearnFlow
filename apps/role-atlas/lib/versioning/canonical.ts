function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, normalize(item)]),
    );
  }
  if (typeof value === "string") return value.normalize("NFC");
  if (typeof value === "number" && !Number.isFinite(value)) throw new Error("NON_FINITE_NUMBER");
  return value;
}

export function canonicalStringify(value: unknown) {
  return JSON.stringify(normalize(value));
}

export async function sha256Hex(value: string | Uint8Array) {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function domainId(prefix: string) {
  return `${prefix}:${crypto.randomUUID()}`;
}

export function projectVersionLabel(createdAt: string, rootHash: string, commitIdentity?: string) {
  const stamp = createdAt.replace(/\D/gu, "").slice(0, 14);
  return `pv-${stamp}-${rootHash.slice(0, 8)}${commitIdentity ? `-${commitIdentity}` : ""}`;
}
