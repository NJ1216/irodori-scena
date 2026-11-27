import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { chooseDirectory } from "../../api";
import { loraApi } from "../../api-lora";
import { useLoraTraining } from "./useLoraTraining";

// Wakes the sequential poller immediately, as when the page becomes visible again.
const pollNow = () =>
  act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
const { api } = vi.hoisted(() => ({ api: { status: vi.fn(), jobs: vi.fn(), inputs: vi.fn(), folderInputs: vi.fn(), start: vi.fn(), cancel: vi.fn() } }));
vi.mock("../../api-lora", () => ({ loraApi: api }));
vi.mock("../../api", () => ({ chooseDirectory: vi.fn() }));
const rows = ["one", "two", "orphan"].map((id) => ({ id, wavName: id === "orphan" ? null : `${id}.wav`, textName: `${id}.txt`, text: "台詞", caption: "", speakerId: "one", durationSeconds: 2, issues: [] }));
beforeEach(() => {
  vi.resetAllMocks();
  api.status.mockResolvedValue({ supported: true });
  api.jobs.mockResolvedValue([]);
  api.inputs.mockResolvedValue({ datasetId: "dataset", rows });
  api.start.mockResolvedValue({ id: "job", name: "テスト", status: "running" });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
async function prepared() {
  const hook = renderHook(() => useLoraTraining());
  await act(async () => {});
  await waitFor(() => expect(hook.result.current.status?.supported).toBe(true));
  await act(async () => {
    await hook.result.current.importFiles([]);
  });
  act(() => {
    hook.result.current.setName("テスト");
    hook.result.current.toggleExcluded("orphan");
  });
  return hook;
}
it("starts once on duplicate clicks, submits every row with explicit exclusion and preserves empty captions", async () => {
  const hook = await prepared();
  let release!: (value: { id: string; name: string; status: string }) => void;
  api.start.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  await act(async () => {
    void hook.result.current.start();
    void hook.result.current.start();
  });
  expect(loraApi.start).toHaveBeenCalledOnce();
  const payload = api.start.mock.calls[0][0];
  expect(payload.rows).toHaveLength(3);
  expect(payload.rows[2].excluded).toBe(true);
  expect(payload.rows[0].caption).toBe("");
  await act(async () => {
    release({ id: "job", name: "テスト", status: "running" });
  });
  expect(hook.result.current.active).toBe(true);
});
it("keeps incomplete numeric drafts and blocks invalid commit", async () => {
  const hook = await prepared();
  act(() => {
    hook.result.current.setAdvanced(true);
    hook.result.current.setSteps("-");
  });
  expect(hook.result.current.steps).toBe("-");
  await act(async () => {
    await hook.result.current.start();
  });
  expect(api.start).not.toHaveBeenCalled();
  expect(hook.result.current.steps).toBe("-");
  expect(hook.result.current.error).toContain("整数");
});
it("keeps a running job when detached and reconnects after reopen; cancellation is explicit", async () => {
  api.jobs.mockResolvedValue([{ id: "job", name: "学習", status: "running", step: 1, totalSteps: 3 }]);
  const first = renderHook(() => useLoraTraining());
  await waitFor(() => expect(first.result.current.active).toBe(true));
  first.unmount();
  expect(api.cancel).not.toHaveBeenCalled();
  const next = renderHook(() => useLoraTraining());
  await waitFor(() => expect(next.result.current.jobs[0]?.step).toBe(1));
  api.cancel.mockResolvedValue({ id: "job", name: "学習", status: "cancelling" });
  await act(async () => {
    await next.result.current.cancel("job");
  });
  expect(api.cancel).toHaveBeenCalledWith("job");
  expect(next.result.current.jobs[0].status).toBe("cancelling");
});
it("does not let a stale poll erase a job accepted during the request", async () => {
  const hook = await prepared();
  const pending: Array<(value: unknown[]) => void> = [];
  api.jobs.mockImplementation(() => new Promise((resolve) => pending.push(resolve)));
  await pollNow();
  await waitFor(() => expect(pending.length).toBeGreaterThan(0));
  const stalePoll = pending[0];
  await act(async () => {
    await hook.result.current.start();
  });
  // Only the poll that began before the start is stale; later polls are not released.
  await act(async () => {
    stalePoll([]);
  });
  expect(hook.result.current.jobs[0].id).toBe("job");
});

it("sends edited settings after closing details instead of silently restoring normal defaults", async () => {
  const hook = await prepared();
  act(() => {
    hook.result.current.changeMode("normal");
    hook.result.current.setAdvanced(true);
  });
  act(() => {
    hook.result.current.setSteps("3");
    hook.result.current.setRate("0.0002");
    hook.result.current.setSeconds("4");
    hook.result.current.setBatch("2");
  });
  act(() => {
    hook.result.current.setAdvanced(false);
  });
  await act(async () => {
    await hook.result.current.start();
  });
  expect(api.start.mock.calls[0][0]).toMatchObject({ mode: "normal", settings: { maxSteps: 3, learningRate: 0.0002, maxSeconds: 4, batchSize: 2 } });
});
it("blocks invalid edited settings even when details is closed and preserves the draft", async () => {
  const hook = await prepared();
  act(() => {
    hook.result.current.setSteps("-");
    hook.result.current.setAdvanced(false);
  });
  await act(async () => {
    await hook.result.current.start();
  });
  expect(api.start).not.toHaveBeenCalled();
  expect(hook.result.current.steps).toBe("-");
  expect(hook.result.current.error).toContain("整数");
});

it("selects a directory once, keeps reviewed rows on cancellation/failure, and replaces only after successful staging", async () => {
  const hook = await prepared();
  vi.mocked(chooseDirectory).mockResolvedValue(null);
  await act(async () => {
    await hook.result.current.importFolder();
  });
  expect(api.folderInputs).not.toHaveBeenCalled();
  expect(hook.result.current.rows).toEqual(rows);
  vi.mocked(chooseDirectory).mockResolvedValue("/fixture/samples");
  api.folderInputs.mockRejectedValue(new Error("フォルダを読めません"));
  await act(async () => {
    await hook.result.current.importFolder();
  });
  expect(hook.result.current.rows).toEqual(rows);
  expect(hook.result.current.error).toContain("フォルダを読めません");
  api.folderInputs.mockResolvedValue({ datasetId: "folder", folderName: "samples", ignoredTextCount: 2, rows: rows.slice(0, 2) });
  await act(async () => {
    await hook.result.current.importFolder();
  });
  expect(api.folderInputs).toHaveBeenLastCalledWith("/fixture/samples");
  expect(hook.result.current.folderName).toBe("samples");
  expect(hook.result.current.ignoredTextCount).toBe(2);
  expect(hook.result.current.excluded.size).toBe(0);
});
it("does not start an ambiguous pair even after transcript correction", async () => {
  api.inputs.mockResolvedValue({ datasetId: "dataset", rows: rows.slice(0, 2).map((row) => ({ ...row, blocked: true })) });
  const hook = await prepared();
  await act(async () => {
    await hook.result.current.start();
  });
  expect(api.start).not.toHaveBeenCalled();
  expect(hook.result.current.error).toContain("曖昧");
});
it("admits one folder picker and one staging request while duplicate import clicks are pending", async () => {
  const hook = await prepared();
  let release!: (value: string | null) => void;
  vi.mocked(chooseDirectory).mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  api.folderInputs.mockResolvedValue({ datasetId: "folder", rows: rows.slice(0, 2) });
  await act(async () => {
    void hook.result.current.importFolder();
    void hook.result.current.importFolder();
  });
  expect(chooseDirectory).toHaveBeenCalledOnce();
  expect(api.folderInputs).not.toHaveBeenCalled();
  expect(hook.result.current.rows).toEqual(rows);
  await act(async () => {
    release("/fixture/samples");
  });
  expect(api.folderInputs).toHaveBeenCalledOnce();
});
