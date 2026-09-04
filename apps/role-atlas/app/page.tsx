import type { Metadata } from "next";
import RoleWorkspace from "./RoleWorkspace";

export const metadata: Metadata = {
  title: "Role Atlas · 岗位智能工作台",
  description: "以版本化岗位快照、证据图谱和结构化引用为基础的岗位智能体工作台。",
};

export default function Home() {
  return <RoleWorkspace />;
}
