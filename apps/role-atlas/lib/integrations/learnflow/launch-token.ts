import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";

export const ROLE_PACKAGE_LAUNCH_PROTOCOL = "role-package-launch.v1" as const;

export type RolePackageLaunchPayload = {
  protocol: typeof ROLE_PACKAGE_LAUNCH_PROTOCOL;
  launchId: string;
  subject: string;
  issuedAt: number;
  expiresAt: number;
  source: "graph_hub" | "role_atlas";
  roleTitle: string;
  packageRef: {
    packageId: string;
    packageVersion: string;
    snapshotId: string;
    rootHash: string;
  };
};

function encoded(value: string) {
  return Buffer.from(value, "utf8").toString("base64url");
}

function secretValue(secret: string) {
  const value = secret.trim();
  if (Buffer.byteLength(value, "utf8") < 32) throw new Error("ROLE_PACKAGE_LAUNCH_SECRET_INVALID");
  return value;
}

export function signRolePackageLaunch(input: {
  secret: string;
  subject: string;
  source: RolePackageLaunchPayload["source"];
  roleTitle: string;
  packageRef: RolePackageLaunchPayload["packageRef"];
  now?: number;
  ttlSeconds?: number;
  launchId?: string;
}) {
  const now = Math.floor(input.now ?? Date.now() / 1000);
  const ttl = Math.min(900, Math.max(60, input.ttlSeconds ?? 300));
  const payload: RolePackageLaunchPayload = {
    protocol: ROLE_PACKAGE_LAUNCH_PROTOCOL,
    launchId: input.launchId || randomUUID(),
    subject: input.subject,
    issuedAt: now,
    expiresAt: now + ttl,
    source: input.source,
    roleTitle: input.roleTitle,
    packageRef: input.packageRef,
  };
  const body = encoded(JSON.stringify(payload));
  const signature = createHmac("sha256", secretValue(input.secret)).update(body).digest("base64url");
  return `${body}.${signature}`;
}

export function verifyRolePackageLaunch(token: string, secret: string, now = Math.floor(Date.now() / 1000)) {
  const [body, supplied, extra] = token.split(".");
  if (!body || !supplied || extra) throw new Error("ROLE_PACKAGE_LAUNCH_TOKEN_INVALID");
  const expected = createHmac("sha256", secretValue(secret)).update(body).digest();
  let actual: Buffer;
  try { actual = Buffer.from(supplied, "base64url"); }
  catch { throw new Error("ROLE_PACKAGE_LAUNCH_TOKEN_INVALID"); }
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) throw new Error("ROLE_PACKAGE_LAUNCH_TOKEN_INVALID");
  let payload: RolePackageLaunchPayload;
  try { payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as RolePackageLaunchPayload; }
  catch { throw new Error("ROLE_PACKAGE_LAUNCH_TOKEN_INVALID"); }
  if (payload.protocol !== ROLE_PACKAGE_LAUNCH_PROTOCOL || !payload.launchId || !payload.subject || !payload.roleTitle
    || !["graph_hub", "role_atlas"].includes(payload.source)
    || !Number.isInteger(payload.issuedAt) || !Number.isInteger(payload.expiresAt)
    || payload.issuedAt > now + 30 || payload.expiresAt <= now || payload.expiresAt - payload.issuedAt > 900
    || !payload.packageRef?.packageId || !payload.packageRef.packageVersion || !payload.packageRef.snapshotId
    || !/^[0-9a-f]{64}$/u.test(payload.packageRef.rootHash)) {
    throw new Error("ROLE_PACKAGE_LAUNCH_TOKEN_INVALID");
  }
  return payload;
}
