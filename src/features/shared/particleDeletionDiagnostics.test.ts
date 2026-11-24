// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { particleCancelled, particleDeletionDiagnostics, recordParticleDeletionDiagnostic } from "./particleDeletionDiagnostics";

afterEach(() => vi.restoreAllMocks());

it("retains the failed preparation stage, elapsed time, and original error outside the notice UI", () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const cause = new Error("HTTP 404 (api-origin)");
  recordParticleDeletionDiagnostic({ target: "cast", phase: "image-fetch", durationMs: 1234.7, count: 1, outcome: "failed", error: cause.message }, cause);
  expect(particleDeletionDiagnostics().at(-1)).toMatchObject({ target: "cast", phase: "image-fetch", durationMs: 1235, outcome: "failed", error: "HTTP 404 (api-origin)" });
  expect(logged).toHaveBeenCalledWith("[SCENA particle deletion]", expect.any(Object), cause);
});

it("records a deliberate cancellation without logging an error", () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
  recordParticleDeletionDiagnostic({ target: "line", phase: "aborted", durationMs: 40, count: 1, outcome: "cancelled", error: "cleared" });
  expect(particleDeletionDiagnostics().at(-1)).toMatchObject({ phase: "aborted", outcome: "cancelled" });
  expect(logged).not.toHaveBeenCalled();
});

it("treats only deliberate abort reasons as cancellations, not timeouts", () => {
  const abortWith = (reason?: unknown) => {
    const controller = new AbortController();
    controller.abort(reason);
    return controller.signal;
  };
  for (const reason of ["cleared", "superseded", "confirmation-expired", "unmounted"]) expect(particleCancelled(abortWith(reason))).toBe(true);
  expect(particleCancelled(abortWith("capture-timeout"))).toBe(false);
  expect(particleCancelled(abortWith())).toBe(false);
  expect(particleCancelled(new AbortController().signal)).toBe(false);
});
