import assert from "node:assert/strict";
import test from "node:test";
import { bundleFromJson, bundleFromZip, bundleToJson, bundleToZip } from "@/lib/packages/archive";
import { compileStaticRolePackage, reconstructBuildResult } from "@/lib/packages/compiler";
import { normalizeRolePackage } from "@/lib/packages/role-package-manifest";
import { validatePackageBundle } from "@/lib/packages/validator";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { preserveStableIdentities } from "@/lib/versioning/identity";
import { snapshotDomainHash } from "@/lib/versioning/snapshot-hash";
import { canonicalStringify, sha256Hex } from "@/lib/versioning/canonical";

test("同一项目版本和发布参数确定性编译为相同岗位包 root hash", async () => {
  const result = bundledRoleSnapshot();
  const input = {
    result,
    packageId: result.packages.rolePackage.packageId,
    packageVersion: "1.2.0",
    sourceProjectVersionId: "pv:test",
    sourceRootHash: "a".repeat(64),
    visibility: "public" as const,
    evidencePolicy: "metadata" as const,
  };
  const [first, second] = await Promise.all([compileStaticRolePackage(input), compileStaticRolePackage(input)]);
  assert.equal(first.bundle.manifest.rootHash, second.bundle.manifest.rootHash);
  assert.equal(bundleToJson(first.bundle), bundleToJson(second.bundle));
  assert.equal(first.validation.valid, true);
  assert.equal(first.bundle.manifest.snapshotAsOf, result.snapshot.asOf);
  assert.equal(first.bundle.manifest.protocolVersion, "3.0.0");
  assert.deepEqual(Object.keys(first.result.packages), ["rolePackage"]);
  assert.equal(first.result.packages.rolePackage.protocolVersion, "3.0.0");
  assert.equal(
    first.result.packages.rolePackage.namespaces.process.objectCount,
    first.result.process.scenarios.length + first.result.process.nodes.length + first.result.process.edges.length + first.result.process.bridges.length,
  );
});

test("旧三包快照只在读取边界升级为统一岗位包且保留版本身份", () => {
  const source = bundledRoleSnapshot();
  const legacy = structuredClone(source) as unknown as { packages: Record<string, unknown> };
  legacy.packages = {
    rolePackage: {
      packageId: source.packages.rolePackage.packageId,
      packageVersion: "1.1.0",
      snapshotId: source.snapshot.id,
      status: "ready",
    },
    workProcessPackage: {
      packageId: "work-process-package:legacy",
      packageVersion: "0.1.0",
      snapshotId: `${source.snapshot.id}:process`,
      status: "candidate",
    },
    compositeSnapshot: {
      id: `composite:${source.snapshot.id}`,
      version: "1.2.0",
      rolePackageId: source.packages.rolePackage.packageId,
      workProcessPackageId: "work-process-package:legacy",
    },
  };
  const normalized = normalizeRolePackage(legacy as unknown as typeof source);
  assert.deepEqual(Object.keys(normalized.packages), ["rolePackage"]);
  assert.equal(normalized.packages.rolePackage.packageVersion, "1.2.0");
  assert.equal(normalized.packages.rolePackage.snapshotId, source.snapshot.id);
  assert.deepEqual(Object.keys(normalized.packages.rolePackage.namespaces).sort(), ["evidence", "process", "semantic"]);
});

test("历史 Static Role Package v2 只在导入边界兼容，重新编译仍输出 v3", async () => {
  const source = bundledRoleSnapshot();
  const compiled = await compileStaticRolePackage({
    result: source,
    packageId: source.packages.rolePackage.packageId,
    packageVersion: "1.2.0",
    visibility: "private",
    evidencePolicy: "full",
  });
  const legacy = structuredClone(compiled.bundle);
  legacy.manifest.protocolVersion = "2.0.0";
  legacy.manifest.rootHash = await sha256Hex(canonicalStringify({ ...legacy.manifest, rootHash: "" }));
  assert.equal((await validatePackageBundle(legacy)).valid, true);
  assert.equal(reconstructBuildResult(legacy).packages.rolePackage.protocolVersion, "3.0.0");
  assert.equal(compiled.bundle.manifest.protocolVersion, "3.0.0");
});

test("JSON 与 ZIP 导入导出保持 manifest 和组件哈希", async () => {
  const result = bundledRoleSnapshot();
  const compiled = await compileStaticRolePackage({
    result,
    packageId: result.packages.rolePackage.packageId,
    packageVersion: "1.2.1",
    visibility: "public",
    evidencePolicy: "metadata",
  });
  const fromJson = bundleFromJson(bundleToJson(compiled.bundle));
  const fromZip = bundleFromZip(bundleToZip(compiled.bundle));
  assert.equal(fromJson.manifest.rootHash, compiled.bundle.manifest.rootHash);
  assert.equal(fromZip.manifest.rootHash, compiled.bundle.manifest.rootHash);
  assert.equal((await validatePackageBundle(fromJson)).valid, true);
  assert.equal((await validatePackageBundle(fromZip)).valid, true);
});

test("组件被篡改后岗位包校验失败，原 root hash 不被重新解释", async () => {
  const result = bundledRoleSnapshot();
  const compiled = await compileStaticRolePackage({ result, packageId: result.packages.rolePackage.packageId, packageVersion: "2.0.0", visibility: "private", evidencePolicy: "full" });
  compiled.bundle.components[compiled.bundle.manifest.entrypoints.semanticGraph] += " ";
  const validation = await validatePackageBundle(compiled.bundle);
  assert.equal(validation.valid, false);
  assert.ok(validation.hardErrors.some((error) => error.includes("哈希不一致")));
});

test("公开岗位包不会以 full 策略泄露私有来源，metadata 策略会遮蔽正文", async () => {
  const result = bundledRoleSnapshot();
  result.sources.assets[0] = { ...result.sources.assets[0], visibility: "project_private" };
  const sourceId = result.sources.assets[0].id;
  const originalText = result.sources.segments.find((segment) => segment.sourceId === sourceId)?.text;
  const full = await compileStaticRolePackage({ result, packageId: result.packages.rolePackage.packageId, packageVersion: "3.0.0", visibility: "public", evidencePolicy: "full" });
  assert.equal(full.validation.valid, false);
  assert.ok(full.validation.hardErrors.some((error) => error.includes("私有工作区证据")));
  const metadata = await compileStaticRolePackage({ result, packageId: result.packages.rolePackage.packageId, packageVersion: "3.0.1", visibility: "public", evidencePolicy: "metadata" });
  assert.equal(metadata.validation.valid, true);
  const sourceComponent = metadata.bundle.components[metadata.bundle.manifest.entrypoints.sources];
  if (originalText) assert.equal(sourceComponent.includes(originalText), false);
  assert.match(sourceComponent, /非公开证据内容未随公开岗位包分发/u);
});

test("父快照中的稳定对象 ID 会跨标签细化保留并迁移所有引用", () => {
  const base = bundledRoleSnapshot();
  const candidate = structuredClone(base);
  const target = candidate.semantic.nodes.find((node) => node.type === "knowledge_skill")!;
  const oldId = target.id;
  target.id = `${oldId}:regenerated`;
  target.aliases = [...target.aliases, target.label];
  const edge = candidate.semantic.edges.find((item) => item.source === oldId || item.target === oldId);
  if (edge?.source === oldId) edge.source = target.id;
  if (edge?.target === oldId) edge.target = target.id;
  const preserved = preserveStableIdentities(base, candidate);
  assert.equal(preserved.replacements.get(`${oldId}:regenerated`), oldId);
  assert.ok(preserved.result.semantic.nodes.some((node) => node.id === oldId));
  if (edge) assert.ok(preserved.result.semantic.edges.some((item) => item.id === edge.id && (item.source === oldId || item.target === oldId)));
});

test("同一静态快照使用不同发布元数据编译后仍保持领域身份", async () => {
  const source = bundledRoleSnapshot();
  const compiled = await compileStaticRolePackage({
    result: source,
    packageId: "role-package:llm-app-engineer-community-mirror",
    packageVersion: "9.8.7",
    visibility: "public",
    evidencePolicy: "metadata",
  });
  const reconstructed = reconstructBuildResult(compiled.bundle);
  assert.equal(await snapshotDomainHash(source), await snapshotDomainHash(reconstructed));
  assert.equal(reconstructed.packages.rolePackage.packageVersion, "9.8.7");
});
