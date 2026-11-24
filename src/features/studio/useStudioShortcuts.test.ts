// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearMultipleSelection, useStudioShortcuts } from "./useStudioShortcuts";

function model() {
  return {
    tab: "script" as const,
    focusedLineId: "line-2",
    selectedLineIds: ["line-1", "line-2"],
    setFocusedLineId: vi.fn(),
    setSelectedLineIds: vi.fn(),
    setSelectionAnchorLineId: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  document.body.replaceChildren();
});

describe("clearMultipleSelection", () => {
  it("keeps only the focused line without changing DOM focus", () => {
    const current = model();
    const input = document.body.appendChild(document.createElement("textarea"));
    input.focus();
    const event = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });

    expect(clearMultipleSelection(event, current)).toBe(true);
    expect(current.setSelectedLineIds).toHaveBeenCalledWith(["line-2"]);
    expect(current.setSelectionAnchorLineId).toHaveBeenCalledWith("line-2");
    expect(document.activeElement).toBe(input);
  });

  it("ignores Escape while a modal is open", () => {
    const current = model();
    document.body.appendChild(document.createElement("div")).className = "modal-backdrop";

    expect(clearMultipleSelection(new KeyboardEvent("keydown", { key: "Escape" }), current)).toBe(false);
    expect(current.setSelectedLineIds).not.toHaveBeenCalled();
  });
});

function shortcutModel() {
  return {
    project: null,
    projectRef: { current: null },
    workspace: null,
    tab: "script",
    focusedLineId: "line-2",
    selectedLineIds: ["line-1", "line-2"],
    selectionAnchorLineId: "line-1",
    busy: null as string | null,
    autoGenerateEnabled: false,
    continuousPlayback: false,
    playingLineId: null as string | null,
    selectedLinePlaybackPending: { current: false },
    selectedLineGenerationActive: false,
    autoRenderInProgress: { current: true },
    autoScrollTarget: "playback" as "playback" | "export",
    autoScrollEnabled: false,
    setProject: vi.fn(),
    setNotice: vi.fn(),
    setFocusedLineId: vi.fn(),
    setSelectedLineIds: vi.fn(),
    setSelectionAnchorLineId: vi.fn(),
    setAutoScrollTarget: vi.fn(),
    setAutoScrollEnabled: vi.fn(),
    requestProjectMenuAction: vi.fn(),
    openWorkspace: vi.fn(),
    saveWorkspace: vi.fn(),
    generateSelectedLines: vi.fn(),
    cancelSelectedLineGeneration: vi.fn(),
    playSelected: vi.fn(),
    deleteSelectedLines: vi.fn(),
    play: vi.fn(),
    playContinuous: vi.fn(),
    stop: vi.fn(),
    toggleAutoGeneration: vi.fn(),
  };
}

function press(code: string, modifiers: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", {
    code,
    key: code.slice(3),
    metaKey: true,
    bubbles: true,
    cancelable: true,
    ...modifiers,
  });
  document.body.dispatchEvent(event);
  return event;
}

describe("project shortcuts", () => {
  it("opens the new-project confirmation with Command-N", () => {
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    const event = press("KeyN");
    expect(event.defaultPrevented).toBe(true);
    expect(current.requestProjectMenuAction).toHaveBeenCalledWith("new");
  });
});

describe("generation cancellation shortcut", () => {
  it("cancels selected-line generation with Escape before changing the selection", () => {
    const current = shortcutModel();
    current.selectedLineGenerationActive = true;
    renderHook(() => useStudioShortcuts(current));
    const event = new KeyboardEvent("keydown", { code: "Escape", key: "Escape", bubbles: true, cancelable: true });

    act(() => document.body.dispatchEvent(event));

    expect(event.defaultPrevented).toBe(true);
    expect(current.cancelSelectedLineGeneration).toHaveBeenCalledOnce();
    expect(current.setSelectedLineIds).not.toHaveBeenCalled();
  });
});

describe("line action shortcuts", () => {
  it("toggles the expression palette with unmodified F3 while a line editor is focused", () => {
    const current = shortcutModel();
    const toggle = vi.fn();
    window.addEventListener("scena-toggle-expression-palette", toggle);
    renderHook(() => useStudioShortcuts(current));
    const editor = document.body.appendChild(document.createElement("div"));
    editor.contentEditable = "true";

    act(() => editor.dispatchEvent(new KeyboardEvent("keydown", { code: "F3", key: "F3", bubbles: true, cancelable: true })));

    expect(toggle).toHaveBeenCalledOnce();
    window.removeEventListener("scena-toggle-expression-palette", toggle);
  });

  it("does not toggle the expression palette during composition, with modifiers, or over a modal", () => {
    const current = shortcutModel();
    const toggle = vi.fn();
    window.addEventListener("scena-toggle-expression-palette", toggle);
    renderHook(() => useStudioShortcuts(current));

    act(() => press("F3", { key: "F3", metaKey: false, isComposing: true }));
    act(() => press("F3", { key: "F3", metaKey: false, shiftKey: true }));
    document.body.appendChild(document.createElement("div")).className = "modal-backdrop";
    act(() => press("F3", { key: "F3", metaKey: false }));

    expect(toggle).not.toHaveBeenCalled();
    window.removeEventListener("scena-toggle-expression-palette", toggle);
  });

  it("routes replace generation through the shared selected-line action during auto render", () => {
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyR", { shiftKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(true, "line-2");
  });

  it("routes append-and-play through the same generation action", () => {
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyP", { altKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(false, "line-2", true);
  });

  it("routes plain command-play through ordered selected-line playback", () => {
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyP"));
    expect(current.playSelected).toHaveBeenCalledWith("line-2");
  });

  it("switches individual playback to continuous playback with Space", () => {
    const current = shortcutModel();
    current.playingLineId = "line-2";
    renderHook(() => useStudioShortcuts(current));
    act(() => press("Space", { metaKey: false }));
    expect(current.playContinuous).toHaveBeenCalledOnce();
    expect(current.stop).not.toHaveBeenCalled();
  });

  it("switches pending generation playback to continuous playback without cancelling generation", () => {
    const current = shortcutModel();
    current.selectedLinePlaybackPending.current = true;
    renderHook(() => useStudioShortcuts(current));
    act(() => press("Space", { metaKey: false }));
    expect(current.playContinuous).toHaveBeenCalledOnce();
    expect(current.stop).not.toHaveBeenCalled();
    expect(current.generateSelectedLines).not.toHaveBeenCalled();
    expect(current.cancelSelectedLineGeneration).not.toHaveBeenCalled();
  });

  it("stops continuous playback with Space", () => {
    const current = shortcutModel();
    current.continuousPlayback = true;
    renderHook(() => useStudioShortcuts(current));
    act(() => press("Space", { metaKey: false }));
    expect(current.stop).toHaveBeenCalledOnce();
    expect(current.playContinuous).not.toHaveBeenCalled();
  });
});

describe("Follow shortcuts", () => {
  it("toggles playback Follow with F during continuous playback", () => {
    const current = shortcutModel();
    current.continuousPlayback = true;
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyF", { metaKey: false }));
    expect(current.setAutoScrollTarget).toHaveBeenCalledWith("playback");
    expect(current.setAutoScrollEnabled).toHaveBeenCalledWith(true);
  });

  it("toggles playback Follow with F while continuous playback is stopped", () => {
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyF", { metaKey: false }));
    expect(current.setAutoScrollTarget).toHaveBeenCalledWith("playback");
    expect(current.setAutoScrollEnabled).toHaveBeenCalledWith(true);
    expect(current.setNotice).toHaveBeenCalledWith("再生FollowをONにしました。連続再生時に発話行を追従します。");
  });

  it("turns Follow off with a second F press", () => {
    const current = shortcutModel();
    current.continuousPlayback = true;
    current.autoScrollEnabled = true;
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyF", { metaKey: false }));
    expect(current.setAutoScrollEnabled).toHaveBeenCalledWith(false);
  });

  it("toggles auto-generation Follow with R while other generation is busy", () => {
    const current = shortcutModel();
    current.busy = "line-1";
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyR", { metaKey: false }));
    expect(current.setAutoScrollTarget).toHaveBeenCalledWith("export");
    expect(current.setAutoScrollEnabled).toHaveBeenCalledWith(true);
    expect(current.toggleAutoGeneration).toHaveBeenCalledOnce();
  });

  it("switches exclusively from playback Follow to auto-generation Follow", () => {
    const current = shortcutModel();
    current.autoScrollEnabled = true;
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyR", { metaKey: false }));
    expect(current.setAutoScrollTarget).toHaveBeenCalledWith("export");
    expect(current.setAutoScrollEnabled).toHaveBeenCalledWith(true);
    expect(current.toggleAutoGeneration).toHaveBeenCalledOnce();
  });

  it("cycles auto-generation from ON Follow through ON UnFollow to OFF", () => {
    const following = shortcutModel();
    following.autoGenerateEnabled = true;
    following.autoScrollEnabled = true;
    following.autoScrollTarget = "export";
    const first = renderHook(() => useStudioShortcuts(following));
    act(() => press("KeyR", { metaKey: false }));
    expect(following.setAutoScrollEnabled).toHaveBeenCalledWith(false);
    expect(following.toggleAutoGeneration).not.toHaveBeenCalled();
    first.unmount();

    const unfollowing = shortcutModel();
    unfollowing.autoGenerateEnabled = true;
    renderHook(() => useStudioShortcuts(unfollowing));
    act(() => press("KeyR", { metaKey: false }));
    expect(unfollowing.toggleAutoGeneration).toHaveBeenCalledOnce();
  });
});

describe("Windows shortcuts", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("maps Command and modifiers directly to Ctrl and modifiers", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyR", { metaKey: false, ctrlKey: true, shiftKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(true, "line-2");
    current.generateSelectedLines.mockClear();
    act(() => press("KeyR", { metaKey: false, ctrlKey: true, altKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(false, "line-2");
    act(() => press("KeyP", { metaKey: false, ctrlKey: true }));
    expect(current.playSelected).toHaveBeenCalledWith("line-2");
    act(() => press("KeyP", { metaKey: false, ctrlKey: true, altKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(false, "line-2", true);
    act(() => press("KeyP", { metaKey: false, ctrlKey: true, shiftKey: true }));
    expect(current.generateSelectedLines).toHaveBeenCalledWith(true, "line-2", true);
  });
  it("runs Ctrl new, search, open, save, and select-all actions", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    const current = shortcutModel();
    current.workspace = { isScratch: true } as never;
    current.projectRef.current = { scenes: [{ lines: [{ id: "line-1" }, { id: "line-2" }] }] } as never;
    const search = vi.fn();
    window.addEventListener("scena-open-script-search", search);
    renderHook(() => useStudioShortcuts(current));

    act(() => press("KeyN", { metaKey: false, ctrlKey: true }));
    act(() => press("KeyF", { metaKey: false, ctrlKey: true }));
    act(() => press("KeyO", { metaKey: false, ctrlKey: true }));
    act(() => press("KeyS", { metaKey: false, ctrlKey: true }));
    act(() => press("KeyA", { metaKey: false, ctrlKey: true }));

    expect(search).toHaveBeenCalledOnce();
    expect(current.requestProjectMenuAction).toHaveBeenCalledWith("new");
    expect(current.openWorkspace).toHaveBeenCalledOnce();
    expect(current.saveWorkspace).toHaveBeenCalledOnce();
    expect(current.setSelectedLineIds).toHaveBeenCalledWith(["line-1", "line-2"]);
    window.removeEventListener("scena-open-script-search", search);
  });
  it("leaves composing and editable text untouched", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    const current = shortcutModel();
    renderHook(() => useStudioShortcuts(current));
    act(() => press("KeyR", { metaKey: false, ctrlKey: true, shiftKey: true, isComposing: true }));
    const input = document.body.appendChild(document.createElement("textarea"));
    act(() => input.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyR", ctrlKey: true, shiftKey: true, bubbles: true })));
    expect(current.generateSelectedLines).not.toHaveBeenCalled();
  });
});
