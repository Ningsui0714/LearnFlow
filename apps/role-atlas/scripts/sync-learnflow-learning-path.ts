import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const learnFlowRoot = process.env.LEARNFLOW_ROOT
  ? resolve(process.env.LEARNFLOW_ROOT)
  : resolve(projectRoot, "../..");
const source = resolve(learnFlowRoot, "frontend/src/learning-path-graph.ts");
const module = await import(pathToFileURL(source).href) as {
  exportOfficialLearningPathContract: () => unknown;
};
const output = resolve(projectRoot, "public/data/learnflow-learning-path.json");
await mkdir(resolve(projectRoot, "public/data"), { recursive: true });
await writeFile(output, `${JSON.stringify(module.exportOfficialLearningPathContract(), null, 2)}\n`, "utf8");
process.stdout.write(`${output}\n`);
