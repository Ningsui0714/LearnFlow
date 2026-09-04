export function publicHref(baseUrl: string | undefined, path: string) {
  const value = String(baseUrl || "").trim();
  if (!value) return path;
  try {
    const base = new URL(value);
    if (!["http:", "https:"].includes(base.protocol)) return path;
    const target = new URL(path, base);
    if (target.origin !== base.origin) throw new Error("PUBLIC_LINK_PATH_INVALID");
    return target.toString();
  } catch {
    return path;
  }
}

/** Cross-product links must not silently resolve against the Graph Hub origin. */
export function roleAtlasHref(baseUrl: string | undefined, path: string) {
  if (!path.startsWith("/") || path.startsWith("//") || /[\\\u0000-\u0020]/u.test(path)) throw new Error("PUBLIC_LINK_PATH_INVALID");
  try {
    const base = new URL(String(baseUrl || "").trim());
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password) throw new Error("PUBLIC_URL_INVALID");
    return new URL(path, base).toString();
  } catch {
    return `/api/navigation/role-atlas?path=${encodeURIComponent(path)}`;
  }
}
