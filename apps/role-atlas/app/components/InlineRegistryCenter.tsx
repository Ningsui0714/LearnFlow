"use client";

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import RegistryCatalog, { type RegistryPackage } from "@/app/registry/RegistryCatalog";

export default function InlineRegistryCenter({ onClose }: { onClose: () => void }) {
  const [packages, setPackages] = useState<RegistryPackage[] | null>(null);
  const [graphHubBaseUrl, setGraphHubBaseUrl] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      const response = await fetch("/api/registry");
      const payload = await response.json() as { packages?: RegistryPackage[]; graphHubBaseUrl?: string; error?: string };
      if (!response.ok) throw new Error(payload.error || "岗位包中心读取失败。");
      setPackages(payload.packages || []);
      setGraphHubBaseUrl(payload.graphHubBaseUrl || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "岗位包中心读取失败。");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  if (error) return <div className="inline-operation-state error"><AlertTriangle size={17} /><b>{error}</b><button onClick={() => void load()}>重试</button><button onClick={onClose}>返回工作台</button></div>;
  if (!packages) return <div className="inline-operation-state"><LoaderCircle className="spin" size={18} /><b>正在读取岗位包中心…</b></div>;
  return <RegistryCatalog initialPackages={packages} graphHubBaseUrl={graphHubBaseUrl} embedded onClose={onClose} onChanged={() => void load()} />;
}
