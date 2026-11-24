import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { DraftJob, ExportJob, StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import type { StudioJobModel } from "./studioJobModel";
import { useDraftJobCancellation } from "./useDraftJobCancellation";
import { useStudioExportActions } from "./useStudioExportActions";

const api = vi.hoisted(() => ({ cancelExportJob: vi.fn(), cancelAiJob: vi.fn(), project: vi.fn() }));
vi.mock("../../api", () => ({ api }));
beforeEach(() => vi.resetAllMocks());

function setup(kind: "export" | "draft") {
  const editSession = new ProjectEditSession(vi.fn());
  const project = { id: "project", scenes: [], characters: [], settings: {} } as unknown as StudioProject;
  editSession.replace(project);
  const setJob = vi.fn();
  const setNotice = vi.fn();
  const setBusy = vi.fn();
  const job = { id: "job", status: "generating" } as DraftJob & ExportJob;
  const hook = renderHook(
    ({ currentJob }) => {
      const cancelDraft = useDraftJobCancellation({ draftJob: currentJob, setNotice, editSession });
      const { cancelExport } = useStudioExportActions({ exportJob: currentJob, setExportJob: setJob, setNotice, editSession } as unknown as StudioJobModel);
      return kind === "export" ? cancelExport : cancelDraft;
    },
    { initialProps: { currentJob: job } },
  );
  return { ...hook, editSession, project, setJob, setNotice, setBusy, job, request: kind === "export" ? api.cancelExportJob : api.cancelAiJob };
}

it.each(["export", "draft"] as const)("leaves %s cancellation state to its progress monitor", async (kind) => {
  const view = setup(kind);
  view.request.mockResolvedValue({ ...view.job, status: "cancelled", cancelRequested: true });
  await act(() => view.result.current());
  expect(view.request).toHaveBeenCalledExactlyOnceWith("job");
  expect(view.setNotice).toHaveBeenCalledOnce();
  expect(view.setJob).not.toHaveBeenCalled();
  expect(view.setBusy).not.toHaveBeenCalled();
  expect(api.project).not.toHaveBeenCalled();
});

it.each(["export", "draft"] as const)("ignores obsolete %s cancellation success and errors", async (kind) => {
  for (const transition of ["project", "completed", "replacement", "unmount"] as const) {
    for (const fails of [false, true]) {
      const view = setup(kind);
      let finish!: () => void;
      view.request.mockImplementation(
        () =>
          new Promise((resolve, reject) => {
            finish = () => (fails ? reject(new Error("late error")) : resolve({ ...view.job, cancelRequested: true }));
          }),
      );
      let pending!: Promise<void>;
      act(() => {
        pending = view.result.current();
      });
      if (transition === "project") view.editSession.replace({ ...view.project, id: "other" });
      else if (transition === "unmount") view.unmount();
      else view.rerender({ currentJob: { ...view.job, ...(transition === "replacement" ? { id: "new" } : { status: "completed" as const }) } });
      await act(async () => {
        finish();
        await pending;
      });
      expect(view.setJob, `${transition}/${fails}`).not.toHaveBeenCalled();
      expect(view.setNotice, `${transition}/${fails}`).not.toHaveBeenCalled();
      expect(view.setBusy, `${transition}/${fails}`).not.toHaveBeenCalled();
      view.unmount();
    }
  }
});
