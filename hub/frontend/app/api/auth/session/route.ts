import { NextResponse } from "next/server";

const backendUrl = (
  process.env.WARDN_HUB_API_INTERNAL_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const privateRevalidationHeaders = {
  "Cache-Control": "private, max-age=0, must-revalidate",
};

export async function GET(request: Request) {
  let response: Response;

  try {
    response = await fetch(`${backendUrl}/api/v1/auth/me`, {
      cache: "no-store",
      headers: {
        ...(request.headers.get("authorization")
          ? { authorization: request.headers.get("authorization") ?? "" }
          : {}),
        ...(request.headers.get("cookie") ? { cookie: request.headers.get("cookie") ?? "" } : {}),
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "Unable to reach the authentication service." },
      { status: 502 },
    );
  }

  if (response.status === 401) {
    return NextResponse.json(null, { headers: privateRevalidationHeaders });
  }

  const body = await response.text();
  return new NextResponse(body, {
    headers: {
      ...privateRevalidationHeaders,
      "Content-Type": response.headers.get("content-type") ?? "application/json",
    },
    status: response.status,
  });
}
