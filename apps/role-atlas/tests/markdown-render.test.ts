import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import MarkdownContent from "@/app/components/MarkdownContent";

test("模型 Markdown 渲染为标题、强调、列表和表格，而不是显示语法符号", () => {
  const markdown = [
    "## 岗位判断",
    "这是 **重点**。",
    "",
    "- 任务一",
    "- 任务二",
    "",
    "| 能力 | 状态 |",
    "| --- | --- |",
    "| RAG | 必需 |",
  ].join("\n");
  const html = renderToStaticMarkup(createElement(MarkdownContent, { text: markdown }));
  assert.match(html, /<h2>岗位判断<\/h2>/);
  assert.match(html, /<strong>重点<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<table>/);
  assert.doesNotMatch(html, /\*\*重点\*\*/);
});

test("Markdown 渲染不执行模型返回的原始 HTML", () => {
  const html = renderToStaticMarkup(createElement(MarkdownContent, { text: "<script>bad()</script>\n\n**安全文本**" }));
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /<strong>安全文本<\/strong>/);
});
