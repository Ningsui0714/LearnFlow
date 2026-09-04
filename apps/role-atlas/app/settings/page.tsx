import type { Metadata } from "next";
import ModelSettings from "./ModelSettings";

export const metadata: Metadata = {
  title: "模型设置 · Role Atlas",
  description: "配置岗位智能体使用的模型供应商与会话级凭据。",
};

export default function SettingsPage() {
  return <ModelSettings />;
}
