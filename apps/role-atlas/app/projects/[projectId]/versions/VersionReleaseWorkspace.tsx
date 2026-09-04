"use client";

import { ArrowLeft, CheckCircle2, Download, GitCompareArrows, History, PackageCheck, Rocket, RotateCcw, Tag } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { SemanticDiff } from "@/lib/versioning/types";

export type VersionSummary = {
  id: string;
  parentVersionId: string | null;
  sourceRunId: string | null;
  sourceKind: string;
  version: string;
  snapshotId: string;
  status: string;
  rootHash: string;
  message: string;
  authorKind: string;
  createdAt: string;
};

export type TagRow = { id: string; name: string; targetVersionId: string; description: string; createdAt: string };
export type ReleaseRow = { id: string; packageLineId: string; sourceProjectVersionId: string | null; packageVersion: string; status: string; artifactRootHash: string | null; error: string | null; publishedAt: string | null; createdAt: string };

export default function VersionReleaseWorkspace({
  project,
  initialVersions,
  initialTags,
  initialReleases,
  embedded = false,
  onClose,
  onChanged,
}: {
  project: { id: string; title: string; headVersionId: string | null; currentReleaseId: string | null };
  initialVersions: VersionSummary[];
  initialTags: TagRow[];
  initialReleases: ReleaseRow[];
  embedded?: boolean;
  onClose?: () => void;
  onChanged?: () => void;
}) {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState(project.headVersionId || initialVersions[0]?.id || "");
  const [compareFrom, setCompareFrom] = useState(initialVersions.find((item) => item.id === selectedId)?.parentVersionId || initialVersions[1]?.id || "");
  const [tagName, setTagName] = useState("");
  const [packageVersion, setPackageVersion] = useState("1.0.0");
  const [visibility, setVisibility] = useState<"private" | "unlisted" | "public">("private");
  const [evidencePolicy, setEvidencePolicy] = useState<"full" | "metadata" | "redacted">("metadata");
  const [diff, setDiff] = useState<SemanticDiff | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const selected = useMemo(() => initialVersions.find((item) => item.id === selectedId), [initialVersions, selectedId]);

  const action = async (key: string, request: Promise<Response>) => {
    setBusy(key); setNotice("");
    try {
      const response = await request;
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "操作失败");
      setNotice("操作已完成，版本与发布记录已更新。");
      if (onChanged) onChanged(); else router.refresh();
      return payload;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败");
      return null;
    } finally { setBusy(""); }
  };

  const loadDiff = async () => {
    if (!compareFrom || !selectedId) return;
    setBusy("diff"); setNotice("");
    try {
      const response = await fetch(`/api/projects/${project.id}/diffs?from=${encodeURIComponent(compareFrom)}&to=${encodeURIComponent(selectedId)}`);
      const payload = await response.json() as { diff?: SemanticDiff; error?: string };
      if (!response.ok || !payload.diff) throw new Error(payload.error || "Diff 生成失败");
      setDiff(payload.diff);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Diff 生成失败"); }
    finally { setBusy(""); }
  };

  const Shell = embedded ? "div" : "main";
  return <Shell className={`version-shell${embedded ? " embedded-operation" : ""}`}>
    <header className="version-topbar">
      {embedded && onClose ? <button type="button" onClick={onClose}><ArrowLeft size={15} /> 返回岗位工作台</button> : <Link href={`/projects/${project.id}`}><ArrowLeft size={15} /> 返回岗位工作台</Link>}
      <span>VERSION · TAG · RELEASE</span>
      {embedded ? <span>页内版本中心</span> : <Link href="/registry">岗位包中心</Link>}
    </header>
    <section className="version-heading">
      <div><span>IMMUTABLE SNAPSHOT HISTORY</span><h1>{project.title}</h1><p>项目历史、Tag 与发布彼此独立；恢复历史不会删除后续版本。</p></div>
      <div className="version-head-facts"><span><b>{initialVersions.length}</b> 个版本</span><span><b>{initialTags.length}</b> 个 Tag</span><span><b>{initialReleases.length}</b> 个 Release</span></div>
    </section>
    {notice ? <div className="version-notice">{notice}</div> : null}
    <div className="version-layout">
      <aside className="version-timeline">
        <header><History size={15} /><span><b>项目版本</b><small>每次构建、迭代与实例化的不可变提交</small></span></header>
        {initialVersions.map((version) => <button key={version.id} className={selectedId === version.id ? "active" : ""} onClick={() => { setSelectedId(version.id); setCompareFrom(version.parentVersionId || ""); setDiff(null); }}>
          <i>{version.id === project.headVersionId ? "HEAD" : version.sourceKind}</i>
          <b>{version.message || version.version}</b>
          <small>{new Date(version.createdAt).toLocaleString("zh-CN")} · {version.snapshotId}</small>
          <code>{version.rootHash.slice(0, 16)}</code>
        </button>)}
      </aside>
      <section className="version-main">
        {selected ? <>
          <article className="version-card selected-version-card">
            <header><span><b>{selected.message || selected.version}</b><small>{selected.status} · {selected.sourceKind}</small></span><code>{selected.id}</code></header>
            <dl><div><dt>Snapshot</dt><dd>{selected.snapshotId}</dd></div><div><dt>Root hash</dt><dd>{selected.rootHash}</dd></div><div><dt>父版本</dt><dd>{selected.parentVersionId || "初始版本"}</dd></div></dl>
            <footer><button disabled={busy === "restore"} onClick={() => void action("restore", fetch(`/api/projects/${project.id}/versions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "restore", targetVersionId: selected.id }) }))}><RotateCcw size={13} /> 从此版本恢复</button></footer>
          </article>

          <div className="version-two-column">
            <article className="version-card">
              <header><GitCompareArrows size={15} /><span><b>语义 Diff</b><small>按稳定对象 ID 与字段路径比较</small></span></header>
              <label>比较来源<select value={compareFrom} onChange={(event) => setCompareFrom(event.target.value)}><option value="">选择历史版本</option>{initialVersions.filter((item) => item.id !== selectedId).map((item) => <option value={item.id} key={item.id}>{item.message || item.version}</option>)}</select></label>
              <button disabled={!compareFrom || busy === "diff"} onClick={() => void loadDiff()}>生成 Diff</button>
              {diff ? <div className="diff-summary"><b>{diff.summary.total} 项语义变化</b><span>+{diff.summary.added} / −{diff.summary.removed} / 修改 {diff.summary.modified} / 重命名 {diff.summary.renamed}</span><small>建议 SemVer：{diff.recommendedBump} · 影响：{diff.impacts.join("、") || "无"}</small></div> : null}
            </article>

            <article className="version-card">
              <header><Tag size={15} /><span><b>标记里程碑</b><small>Tag 是指向当前版本的不可变名称</small></span></header>
              <label>Tag 名称<input value={tagName} onChange={(event) => setTagName(event.target.value)} placeholder="例如：首个可用版" /></label>
              <button disabled={!tagName.trim() || busy === "tag"} onClick={() => void action("tag", fetch(`/api/projects/${project.id}/tags`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: tagName, targetVersionId: selected.id }) }))}>创建 Tag</button>
              <div className="tag-list">{initialTags.filter((tag) => tag.targetVersionId === selected.id).map((tag) => <span key={tag.id}>{tag.name}</span>)}</div>
            </article>
          </div>

          <article className="version-card release-builder">
            <header><PackageCheck size={15} /><span><b>发布岗位图谱仓库</b><small>版本化编译、校验，并托管到 Graph Hub</small></span></header>
            <div className="release-form"><label>SemVer<input value={packageVersion} onChange={(event) => setPackageVersion(event.target.value)} /></label><label>可见范围<select value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)}><option value="private">私有</option><option value="unlisted">不公开列出</option><option value="public">公开</option></select></label><label>证据策略<select value={evidencePolicy} onChange={(event) => setEvidencePolicy(event.target.value as typeof evidencePolicy)}><option value="metadata">只公开元数据</option><option value="redacted">脱敏</option><option value="full">完整</option></select></label></div>
            <div className="release-publish-actions">
              <button className="secondary" disabled={busy === "prepare" || busy === "publish-to-hub"} onClick={() => void action("prepare", fetch("/api/releases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "prepare", projectId: project.id, projectVersionId: selected.id, packageVersion, visibility, evidencePolicy }) }))}>仅编译并校验</button>
              <button disabled={busy === "publish-to-hub"} title="编译、校验并作为公开仓库立即发布" onClick={() => void action("publish-to-hub", fetch("/api/releases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "publish_to_hub", projectId: project.id, projectVersionId: selected.id, packageVersion, evidencePolicy }) }))}><Rocket size={13} /> {busy === "publish-to-hub" ? "正在发布…" : "发布到 Graph Hub（公开）"}</button>
            </div>
          </article>
        </> : <p>项目尚无不可变版本。</p>}
      </section>
      <aside className="release-list">
        <header><PackageCheck size={15} /><span><b>Release</b><small>发布失败不会改变当前推荐版本</small></span></header>
        {initialReleases.map((release) => <article key={release.id} className={release.id === project.currentReleaseId ? "current" : ""}>
          <span><b>v{release.packageVersion}</b><i>{release.status}</i></span>
          <small>{new Date(release.createdAt).toLocaleString("zh-CN")}</small>
          {release.error ? <p>{release.error}</p> : null}
          <div>
            {release.status === "ready" ? <button disabled={busy === release.id} onClick={() => void action(release.id, fetch("/api/releases", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "publish", releaseId: release.id }) }))}><CheckCircle2 size={12} /> 发布</button> : null}
            {release.status === "published" && release.id !== project.currentReleaseId ? <button disabled={busy === `rollback:${release.id}`} onClick={() => void action(`rollback:${release.id}`, fetch("/api/releases", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "rollback", packageLineId: release.packageLineId, targetReleaseId: release.id, expectedCurrentReleaseId: project.currentReleaseId }) }))}><RotateCcw size={12} /> 回滚到此版</button> : null}
            {release.artifactRootHash && ["ready", "published", "deprecated"].includes(release.status) ? <a href={`/api/releases/${release.id}/export`}><Download size={12} /> 导出</a> : null}
          </div>
        </article>)}
      </aside>
    </div>
  </Shell>;
}
