export type ApiFailureKind = "priority-interruption" | "http";

export class ApiConnectionError extends Error {
  readonly name = "ApiConnectionError";
}

export class ApiError extends Error {
  readonly name = "ApiError";

  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
    readonly code: string | undefined,
    readonly kind: ApiFailureKind,
  ) {
    super(message);
  }
}

export function apiFailureKind(_path: string, _method: string, _status: number, detail: unknown): ApiFailureKind {
  const code = detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as { code?: unknown }).code : undefined;
  return code === "priority_interruption" ? "priority-interruption" : "http";
}
