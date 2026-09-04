import { resolve } from "node:path";
import { exportStaticRolePackageFile } from "../lib/packages/file-export";

function argument(name: string) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const sourceDirectory = argument("--source");
const outputFile = argument("--out");

if (!sourceDirectory || !outputFile) {
  console.error("用法：npx tsx scripts/export-role-package-file.ts --source <岗位包版本目录> --out <输出.role-package.json>");
  process.exitCode = 2;
} else {
  const receipt = await exportStaticRolePackageFile({
    sourceDirectory: resolve(sourceDirectory),
    outputFile: resolve(outputFile),
  });
  console.log(JSON.stringify(receipt, null, 2));
}
