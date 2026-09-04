"use client";

import { Download, MessageCircle } from "lucide-react";
import { useState } from "react";

export default function HubRepositoryActions({ releaseId }: { releaseId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const launch = async () => {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/integrations/learnflow/launch", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ releaseId, source: "graph_hub" }) });
      const payload = await response.json() as { launchUrl?: string; error?: string };
      if (!response.ok || !payload.launchUrl) throw new Error(payload.error || "无法进入 LearnFlow");
      window.location.assign(payload.launchUrl);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法进入 LearnFlow"); }
    finally { setBusy(false); }
  };
  return <div className="hub-repo-actions"><button type="button" onClick={() => void launch()} disabled={busy}><MessageCircle size={14} /> {busy ? "正在连接…" : "在 LearnFlow 中使用"}</button><a href={`/api/releases/${releaseId}/export`}><Download size={14} /> 下载岗位包</a>{error ? <small>{error}</small> : null}</div>;
}
