import type { Metadata } from "next";
import ColdStartWorkspace from "./ColdStartWorkspace";

export const metadata: Metadata = {
  title: "新建岗位项目 · Role Atlas",
  description: "从来源证据生成岗位结构、工作事理与可追溯的首个岗位包版本。",
};

export default async function NewProjectPage({
  searchParams,
}: {
  searchParams: Promise<{
    project?: string;
    conversation?: string;
    role?: string;
    description?: string;
    market?: string;
    skill?: string;
  }>;
}) {
  return <ColdStartWorkspace initialQuery={await searchParams} />;
}
