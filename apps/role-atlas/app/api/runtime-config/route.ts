import { runtimeConfigStatus } from "@/lib/server-runtime-config";
import { workerRuntimeBindings } from "@/lib/worker-runtime-bindings";

export const runtime = "edge";

export async function GET() {
  return Response.json(runtimeConfigStatus(workerRuntimeBindings()), {
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
}
