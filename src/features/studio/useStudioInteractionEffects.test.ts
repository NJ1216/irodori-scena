// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useStudioInteractionEffects } from "./useStudioInteractionEffects";

function followModel() {
  return {
    project: null,
    autoGenerateEnabled: false,
    busy: null,
    exportJob: null,
    continuousPlaybackWaiters: { current: new Set<() => void>() },
    autoGenerateEnabledRef: { current: false },
    busyRef: { current: null },
    autoScrollEnabled: true,
    playbackHoverFollow: false,
    exportHoverFollow: false,
    autoScrollTarget: "playback",
    continuousPlayback: true,
    setAutoScrollEnabled: vi.fn(),
    setPlaybackHoverFollow: vi.fn(),
    setExportHoverFollow: vi.fn(),
    setNotice: vi.fn(),
    setStatusNotice: vi.fn(),
    processAutoRenderQueue: vi.fn(),
  };
}

afterEach(() => document.body.replaceChildren());

it("keeps playback follow on while the wheel scrolls inside an open dialog", () => {
  const model = followModel();
  renderHook(() => useStudioInteractionEffects(model as never));
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  const content = document.createElement("div");
  backdrop.append(content);
  document.body.append(backdrop);

  content.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));

  expect(model.setAutoScrollEnabled).not.toHaveBeenCalled();
  expect(model.setStatusNotice).not.toHaveBeenCalled();
});

it("turns follow off on manual script scrolling with a status notice only", () => {
  const model = followModel();
  renderHook(() => useStudioInteractionEffects(model as never));

  document.body.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));

  expect(model.setAutoScrollEnabled).toHaveBeenCalledWith(false);
  expect(model.setStatusNotice).toHaveBeenCalledWith("手動スクロールを検出したため、自動スクロールを解除しました。");
  expect(model.setNotice).not.toHaveBeenCalled();
});
