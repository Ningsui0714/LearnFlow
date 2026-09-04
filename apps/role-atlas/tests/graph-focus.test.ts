import assert from "node:assert/strict";
import test from "node:test";
import { graphFocusStates } from "@/lib/hub/graph-focus";

test("聚焦包含双向一跳邻居，淡化无关节点并保留原关系方向", () => {
  const nodes = ["a", "b", "c", "d"].map(id => ({ id }));
  const edges = [{ id: "ab", source: "a", target: "b" }, { id: "ca", source: "c", target: "a" }, { id: "bd", source: "b", target: "d" }];
  const states = graphFocusStates(nodes, edges, "a");
  assert.deepEqual(states.a, ["selected"]);
  assert.deepEqual(states.b, ["related"]);
  assert.deepEqual(states.c, ["related"]);
  assert.deepEqual(states.d, ["inactive"]);
  assert.deepEqual(states.ca, ["related"]);
  assert.deepEqual(states.bd, ["inactive"]);
  assert.equal(edges[1].source, "c");
  assert.ok(Object.values(graphFocusStates(nodes, edges, "missing")).every(value => !value.length));
});
