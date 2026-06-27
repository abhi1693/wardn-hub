import { HubApiError } from "@/lib/api/hub";

export type ProtectedLoadState = "loading" | "ready" | "auth" | "denied" | "error";

export function protectedStateFromError(error: unknown): Exclude<ProtectedLoadState, "loading" | "ready"> {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}
