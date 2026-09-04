"use client";

import { ArrowLeft, SearchCheck, ShieldCheck, Zap } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PROVIDERS, PROVIDER_SESSION_KEY } from "@/lib/providers";
import { SEARCH_PROVIDERS, SEARCH_PROVIDER_SESSION_KEY } from "@/lib/search/providers";
import type { RuntimeConfigStatus } from "@/lib/runtime-config";

export default function ModelSettings({ embedded = false, onClose }: { embedded?: boolean; onClose?: () => void }) {
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeConfigStatus | null>(null);

  useEffect(() => {
    sessionStorage.removeItem(PROVIDER_SESSION_KEY);
    sessionStorage.removeItem(SEARCH_PROVIDER_SESSION_KEY);
    const controller = new AbortController();
    fetch("/api/runtime-config", { signal: controller.signal })
      .then((response) => response.json() as Promise<RuntimeConfigStatus>)
      .then(setRuntimeStatus)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const modelName = runtimeStatus?.model.configured
    ? `${PROVIDERS[runtimeStatus.model.provider]?.name || runtimeStatus.model.provider} · ${runtimeStatus.model.model}`
    : "后台尚未接入模型";
  const searchName = runtimeStatus?.search.configured
    ? SEARCH_PROVIDERS[runtimeStatus.search.provider]?.name || runtimeStatus.search.provider
    : "后台尚未接入搜索服务";
  const Shell = embedded ? "div" : "main";

  return (
    <Shell className={`settings-shell${embedded ? " embedded-operation" : ""}`}>
      <header className="settings-topbar">
        {embedded && onClose ? <button type="button" className="back-link" onClick={onClose}><ArrowLeft size={15} /> 返回岗位工作台</button> : <Link href="/" className="back-link"><ArrowLeft size={15} /> 返回岗位工作台</Link>}
        <span>Role Atlas / 平台运行时</span>
      </header>
      <section className="settings-layout">
        <aside className="settings-nav">
          <div className="settings-brand"><span>R</span><b>平台运行时</b></div>
          <button className="active"><Zap size={15} /> 智能模型</button>
          <button><SearchCheck size={15} /> 联网检索</button>
        </aside>
        <div className="settings-content">
          <div className="settings-heading" id="model-runtime">
            <span className="eyebrow">PLATFORM MANAGED</span>
            <h1>模型由平台后台统一接入</h1>
            <p>账户无需填写 API Key，也不能覆盖模型、服务地址或搜索供应商。密钥只保存在服务器环境中。</p>
          </div>
          <section className="settings-panel">
            <div className="panel-title">
              <div><h2>{modelName}</h2><p>用于岗位研究、岗位包生成与语义处理</p></div>
              <ShieldCheck size={20} />
            </div>
            <div className="security-note"><ShieldCheck size={16} /><span><b>后台总控</b><small>浏览器不会读取、保存或提交供应商 API Key。</small></span></div>
          </section>
          <section className="settings-panel" id="web-research">
            <div className="panel-title">
              <div><h2>{searchName}</h2><p>用于公开资料检索与证据补充，同样由后台统一配置。</p></div>
              <SearchCheck size={20} />
            </div>
          </section>
        </div>
      </section>
    </Shell>
  );
}
