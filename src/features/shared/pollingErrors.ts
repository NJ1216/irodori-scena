import { ApiConnectionError, ApiError } from "../../api-error";

/** Failures worth retrying while polling a long-running job: connection loss, timeout, rate limit and server errors. */
export function retryableStatusFailure(error: unknown): boolean {
  return error instanceof ApiConnectionError || (error instanceof ApiError && ([408, 429].includes(error.status) || (error.status >= 500 && error.status < 600)));
}
