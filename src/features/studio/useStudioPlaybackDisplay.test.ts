// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useStudioPlaybackDisplay } from "./useStudioPlaybackDisplay";

const scroll = vi.fn();
const model = { tab: "script" as const, continuousPlayback: true, autoScrollTarget: "playback" as const, autoScrollEnabled: true, playbackHoverFollow: false, exportHoverFollow: false, playingLineId: "tail|head", generatingLineId: null };

beforeEach(() => {
  scroll.mockClear();
  HTMLElement.prototype.scrollIntoView = scroll;
});

it("follows the cue head when timeline events list the later member first", () => {
  document.body.innerHTML = '<article data-line-id="head" class="is-cue-member is-cue-head"></article><article data-line-id="tail" class="is-cue-member is-cue-tail"></article>';
  renderHook(() => useStudioPlaybackDisplay(model));
  expect(scroll).toHaveBeenCalledOnce();
  expect(scroll.mock.contexts[0]).toBe(document.querySelector('[data-line-id="head"]'));
  expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
});

it("retains the latest active line for overlapping independent utterances", () => {
  document.body.innerHTML = '<article data-line-id="head" class="is-cue-member is-cue-head"></article><article data-line-id="tail"></article>';
  renderHook(() => useStudioPlaybackDisplay(model));
  expect(scroll.mock.contexts[0]).toBe(document.querySelector('[data-line-id="tail"]'));
});
