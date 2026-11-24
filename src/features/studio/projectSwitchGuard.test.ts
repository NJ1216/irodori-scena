import type { SetStateAction } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PROJECT_SWITCH_CLICK_GUARD_MS, releaseProjectSwitchBusy } from "./projectSwitchGuard";

describe("project switch click guard", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps insertion blocked until residual clicks have passed", () => {
    vi.useFakeTimers();
    let busy: string | null = "open-workspace";
    const setBusy = vi.fn((update: SetStateAction<string | null>) => {
      busy = typeof update === "function" ? update(busy) : update;
    });

    releaseProjectSwitchBusy(setBusy, "open-workspace");
    vi.advanceTimersByTime(PROJECT_SWITCH_CLICK_GUARD_MS - 1);
    expect(busy).toBe("open-workspace");
    vi.advanceTimersByTime(1);
    expect(busy).toBeNull();
  });

  it("does not clear a newer operation", () => {
    vi.useFakeTimers();
    let busy: string | null = "open-workspace";
    const setBusy = vi.fn((update: SetStateAction<string | null>) => {
      busy = typeof update === "function" ? update(busy) : update;
    });

    releaseProjectSwitchBusy(setBusy, "open-workspace");
    busy = "draft";
    vi.advanceTimersByTime(PROJECT_SWITCH_CLICK_GUARD_MS);
    expect(busy).toBe("draft");
  });
});
