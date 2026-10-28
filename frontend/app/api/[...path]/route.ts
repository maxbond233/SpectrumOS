import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function forward(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (!["GET", "HEAD"].includes(request.method) &&
      (!origin || new URL(origin).host !== request.headers.get("host"))) {
    return Response.json({detail: "请求来源无效"}, {status: 403});
  }
  const backend = process.env.SPECTRUM_API_URL ?? "http://127.0.0.1:8078";
  const headers = new Headers({"Content-Type": "application/json"});
  if (process.env.SPECTRUM_API_TOKEN) {
    headers.set("Authorization", `Bearer ${process.env.SPECTRUM_API_TOKEN}`);
  }
  const response = await fetch(`${backend}${request.nextUrl.pathname}${request.nextUrl.search}`, {
    method: request.method, headers, cache: "no-store", signal: request.signal,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
  });
  const outgoing = new Headers();
  for (const key of ["content-type", "content-disposition", "cache-control", "x-accel-buffering"]) {
    const value = response.headers.get(key);
    if (value) outgoing.set(key, value);
  }
  return new Response(response.body, {status: response.status, headers: outgoing});
}

export { forward as GET, forward as POST, forward as PATCH };
