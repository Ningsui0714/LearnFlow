import assert from "node:assert/strict";
import test from "node:test";
import { publicHref, roleAtlasHref } from "@/lib/public-links";

test("跨域产品入口使用配置的公共地址", () => {
  assert.equal(publicHref("https://roles.learnflow.club", "/"), "https://roles.learnflow.club/");
  assert.equal(publicHref("https://roles.learnflow.club/", "/projects/new"), "https://roles.learnflow.club/projects/new");
});

test("跨产品入口缺少配置时进入明确诊断入口而不是当前站点根路径", () => {
  for (const base of ["", "not a url", "ftp://example.test", "https://user:password@example.test"]) {
    assert.equal(roleAtlasHref(base, "/projects/new"), "/api/navigation/role-atlas?path=%2Fprojects%2Fnew");
  }
  assert.equal(roleAtlasHref("https://roles.example.test", "/projects/new"), "https://roles.example.test/projects/new");
  assert.throws(() => roleAtlasHref("https://roles.example.test", "//attacker.test"), /PUBLIC_LINK_PATH_INVALID/);
  assert.throws(() => roleAtlasHref("https://roles.example.test", "/\\attacker.test"), /PUBLIC_LINK_PATH_INVALID/);
});

test("缺少或非法公共地址时保留本地相对路径", () => {
  assert.equal(publicHref("", "/"), "/");
  assert.equal(publicHref("not a url", "/"), "/");
  assert.equal(publicHref("ftp://roles.learnflow.club", "/"), "/");
});
