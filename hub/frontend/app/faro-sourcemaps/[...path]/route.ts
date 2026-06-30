import { readFile } from "node:fs/promises";
import path from "node:path";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path?: string[] }> | { path?: string[] };
};

function isInternalHost(request: NextRequest) {
  const host = request.headers.get("host")?.split(":")[0]?.toLowerCase();

  return Boolean(
    host &&
      (host.endsWith(".svc") ||
        host.endsWith(".svc.cluster.local") ||
        host === "wardn-hub-frontend" ||
        host === "wardn-hub-frontend.wardn"),
  );
}

export async function GET(request: NextRequest, context: RouteContext) {
  if (!isInternalHost(request)) {
    return new Response("Not found", { status: 404 });
  }

  const params = await context.params;
  const requestedPath = params.path?.join("/") ?? "";

  if (!requestedPath.startsWith("_next/static/") || !requestedPath.endsWith(".map")) {
    return new Response("Not found", { status: 404 });
  }

  const root = path.resolve(process.cwd(), ".next", "faro-sourcemaps");
  const filePath = path.resolve(root, requestedPath);
  const standaloneRoot = path.resolve(process.cwd(), "..", "faro-sourcemaps");
  const standaloneFilePath = path.resolve(standaloneRoot, requestedPath);

  if (
    !filePath.startsWith(``) ||
    !standaloneFilePath.startsWith(``)
  ) {
    return new Response("Not found", { status: 404 });
  }

  try {
    const body = await readFile(filePath).catch(() => readFile(standaloneFilePath));
    return new Response(new Uint8Array(body), {
      headers: {
        "Cache-Control": "private, max-age=31536000, immutable",
        "Content-Type": "application/json; charset=utf-8",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
