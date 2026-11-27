import { expect, it } from "vitest";
import { ApiConnectionError, ApiError } from "../../api-error";
import { retryableStatusFailure } from "./pollingErrors";

it("retries only connection, timeout, rate-limit and server failures", () => {
  expect(retryableStatusFailure(new ApiConnectionError("offline"))).toBe(true);
  for (const status of [408, 429, 500, 503]) expect(retryableStatusFailure(new ApiError("x", status, null, undefined, "http"))).toBe(true);
  expect(retryableStatusFailure(new ApiError("x", 404, null, undefined, "http"))).toBe(false);
  expect(retryableStatusFailure(new Error("x"))).toBe(false);
});
