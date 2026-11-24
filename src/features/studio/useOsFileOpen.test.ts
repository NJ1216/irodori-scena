import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const desktop = vi.hoisted(() => ({ listener: undefined as (() => void) | undefined, invoke: vi.fn() }));
vi.mock("../../api", () => ({ isDesktopRuntime: true }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: desktop.invoke }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (_name: string, listener: () => void) => {
    desktop.listener = listener;
    return vi.fn();
  }),
}));

import { useOsFileOpen } from "./useOsFileOpen";

function model() {
  return {
    project: {},
    setNotice: vi.fn(),
    busyRef: { current: null },
    autoRenderInProgress: { current: false },
    selectedLineGenerationActive: false,
    exportJob: null,
    stopAutoGeneration: vi.fn(),
    cancelSelectedLineGeneration: vi.fn(),
    cancelExport: vi.fn(),
    openWorkspace: vi.fn(async () => undefined),
    prepareCastImport: vi.fn(async () => undefined),
  };
}

describe("useOsFileOpen", () => {
  beforeEach(() => {
    desktop.listener = undefined;
    desktop.invoke.mockReset();
  });

  it("drains startup requests and then handles runtime events", async () => {
    desktop.invoke.mockResolvedValueOnce([["/tmp/起動時.scena"]]).mockResolvedValueOnce([["一.scenacast", "二.SCENACAST"]]);
    const target = model();
    renderHook(() => useOsFileOpen(target as never));
    await waitFor(() => expect(target.openWorkspace).toHaveBeenCalledWith(false, "/tmp/起動時.scena"));
    desktop.listener?.();
    await waitFor(() => expect(target.prepareCastImport).toHaveBeenCalledWith(["一.scenacast", "二.SCENACAST"]));
    expect(desktop.invoke).toHaveBeenCalledTimes(2);
  });

  it("keeps startup requests until the initial project is ready", async () => {
    desktop.invoke.mockResolvedValueOnce([["/tmp/保留.scena"]]);
    const target = model();
    target.project = null as never;
    const { rerender } = renderHook(({ current }) => useOsFileOpen(current as never), { initialProps: { current: target } });
    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledOnce());
    expect(target.openWorkspace).not.toHaveBeenCalled();
    const ready = { ...target, project: {} };
    rerender({ current: ready });
    await waitFor(() => expect(target.openWorkspace).toHaveBeenCalledWith(false, "/tmp/保留.scena"));
  });
});
