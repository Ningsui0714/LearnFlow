import { strFromU8, strToU8, unzipSync, zipSync } from "fflate";
import { canonicalStringify } from "@/lib/versioning/canonical";
import type { StaticRolePackageBundle } from "./types";

export function bundleToJson(bundle: StaticRolePackageBundle) {
  return canonicalStringify(bundle);
}

export function bundleFromJson(value: string | Uint8Array) {
  const text = typeof value === "string" ? value : new TextDecoder().decode(value);
  return JSON.parse(text) as StaticRolePackageBundle;
}

export function bundleToZip(bundle: StaticRolePackageBundle) {
  const files: Record<string, Uint8Array> = {
    "manifest.json": strToU8(canonicalStringify(bundle.manifest)),
  };
  for (const [path, content] of Object.entries(bundle.components)) files[path] = strToU8(content);
  return zipSync(files, { level: 6 });
}

export function bundleFromZip(bytes: Uint8Array): StaticRolePackageBundle {
  const files = unzipSync(bytes, { filter: (file) => {
    if (file.name.startsWith("/") || file.name.includes("..") || file.name.includes("\\")) throw new Error("UNSAFE_ARCHIVE_PATH");
    return true;
  } });
  if (!files["manifest.json"]) throw new Error("MANIFEST_NOT_FOUND");
  const manifest = JSON.parse(strFromU8(files["manifest.json"])) as StaticRolePackageBundle["manifest"];
  const components = Object.fromEntries(Object.entries(files)
    .filter(([path]) => path !== "manifest.json")
    .map(([path, content]) => [path, strFromU8(content)]));
  return { manifest, components };
}
