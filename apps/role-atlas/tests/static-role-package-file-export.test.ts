import assert from "node:assert/strict";
import { cp, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { bundleFromJson } from "@/lib/packages/archive";
import { exportStaticRolePackageFile } from "@/lib/packages/file-export";
import { validatePackageBundle } from "@/lib/packages/validator";

const golden = resolve("packages/golden/llm-app-engineer/1.0.0");

test("静态岗位包目录确定性导出为 LearnFlow 可消费的单文件 bundle", async () => {
  const root = await mkdtemp(join(tmpdir(), "role-package-export-"));
  const outputFile = join(root, "llm-app-engineer.role-package.json");
  const receipt = await exportStaticRolePackageFile({ sourceDirectory: golden, outputFile });
  const bundle = bundleFromJson(await readFile(outputFile, "utf8"));

  assert.equal(receipt.protocol, "role-package-file-export.v1");
  assert.equal(receipt.rootHash, bundle.manifest.rootHash);
  assert.equal((await validatePackageBundle(bundle)).valid, true);
  await assert.rejects(
    exportStaticRolePackageFile({ sourceDirectory: golden, outputFile }),
    /OUTPUT_EXISTS/,
  );
});

test("组件被篡改的目录不能导出", async () => {
  const root = await mkdtemp(join(tmpdir(), "role-package-tamper-"));
  const source = join(root, "source");
  await cp(golden, source, { recursive: true });
  await writeFile(join(source, "semantic-graph.json"), "{}", "utf8");

  await assert.rejects(
    exportStaticRolePackageFile({ sourceDirectory: source, outputFile: join(root, "bad.role-package.json") }),
    /PACKAGE_INVALID:.*哈希不一致/u,
  );
});
