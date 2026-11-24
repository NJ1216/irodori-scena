import { expect, it } from "vitest";
import { additionFinished, additionState, additionError } from "./modelAddition";

it("waits for preparation and verification after file transfer finishes", () => {
  for (const state of ["preparing", "waiting-model", "verifying"]) {
    expect(additionFinished({ state: "complete", preparation: { state, message: "checking" } })).toBe(false);
  }
  expect(additionFinished({ state: "complete", preparation: { state: "complete", message: "ready" } })).toBe(true);
});

it("preserves preparation failure and interrupted state instead of reporting success", () => {
  for (const state of ["failed", "cancelled", "interrupted"]) {
    const status = { state: "complete", preparation: { state, message: "reason" } };
    expect(additionFinished(status)).toBe(true);
    expect(additionState(status)).toBe(state);
    expect(additionError(status)).toBe("reason");
  }
  expect(additionState({ state: "complete" })).toBe("complete");
});
