// @vitest-environment jsdom
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { Profiler, useEffect } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { StudioProject } from "../../types";
import { useProjectEditSession } from "./useProjectEditSession";
import { useStudioHistory } from "./useStudioHistory";
import { clearCandidateState } from "./projectCandidateState";
import type { ProjectEditSession } from "./projectEditSession";
import { EmojiTextArea } from "../script/EmojiTextArea";

const mocks = vi.hoisted(() => ({
  saveProject: vi.fn(),
  patchProjectMetadata: vi.fn(),
  patchProjectSettings: vi.fn(),
  patchProjectLine: vi.fn(),
  changeHistory: vi.fn(),
  historyStatus: vi.fn(),
  project: vi.fn(),
  clearCandidates: vi.fn(),
}));
vi.mock("../../api", () => ({ api: mocks, HISTORY_CHANGED_EVENT: "test-history" }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function setup() {
  const notice = vi.fn();
  const hook = renderHook(() => {
    const session = useProjectEditSession(notice);
    const history = useStudioHistory({ tab: "script", busy: null, editSession: session.editSession, setNotice: notice });
    return { ...session, ...history };
  });
  act(() => hook.result.current.editSession.replace(structuredClone(fixture) as StudioProject));
  return { ...hook, notice, session: hook.result.current.editSession };
}
const line = (project: StudioProject) => project.scenes[0].lines[0];
beforeEach(() => {
  vi.resetAllMocks();
  mocks.saveProject.mockImplementation(async (project) => ({ ...project, revision: 12 }));
  mocks.patchProjectMetadata.mockResolvedValue({ revision: 12 });
  mocks.patchProjectSettings.mockResolvedValue({ revision: 12 });
  mocks.patchProjectLine.mockResolvedValue({ revision: 12 });
  mocks.historyStatus.mockResolvedValue({ canUndo: true, canRedo: true, busy: false });
  mocks.changeHistory.mockResolvedValue({ canUndo: false, canRedo: true, busy: false });
});

it("rebases the latest pending save on a completed generation while retaining an input draft", async () => {
  const { session, result } = setup();
  const started = deferred<void>(),
    response = deferred<StudioProject>();
  const generated = structuredClone(session.savedProject()!);
  line(generated).takes.push({ ...line(generated).takes[0], id: "new-take" });
  line(generated).selectedTakeId = "new-take";
  let operation!: Promise<StudioProject | undefined>;
  act(() => {
    operation = session.requestProject(() => {
      started.resolve();
      return response.promise;
    });
  });
  await act(() => started.promise);
  let first!: Promise<boolean>, latest!: Promise<boolean>;
  act(() => {
    session.update((project) => ({ ...project, title: "one" }));
    first = session.save();
    session.update((project) => ({ ...project, title: "latest" }));
    latest = session.save();
    session.draftLine(line(generated).id, { text: "変換中" });
  });
  expect(mocks.saveProject).not.toHaveBeenCalled();
  expect(result.current.projectSavePendingCount.current).toBe(2);
  await act(async () => {
    response.resolve(generated);
    await operation;
    expect(await first).toBe(true);
    expect(await latest).toBe(true);
  });
  expect(mocks.saveProject).toHaveBeenCalledOnce();
  const saved = mocks.saveProject.mock.calls[0][0] as StudioProject;
  expect(saved.title).toBe("latest");
  expect(line(saved).takes.at(-1)?.id).toBe("new-take");
  expect(line(saved).text).toBe(line(generated).text);
  expect(line(result.current.project!).text).toBe(line(generated).text);
  expect(line(session.projectRef.current!).text).toBe("変換中");
  expect(result.current.projectSavedVersion.current).toBe(2);
  expect(session.serverRevision).toBe(12);
});

it.each(["switch", "undo"])("waits for committed saves before %s and aborts after a failed save", async (kind) => {
  const { session, result } = setup();
  const saving = deferred<{ revision: number }>();
  mocks.patchProjectMetadata.mockReturnValueOnce(saving.promise);
  const switchProject = vi.fn(async () => ({ ...session.savedProject()!, id: "new-project" }));
  let saved!: Promise<boolean>, operation!: Promise<unknown>;
  act(() => {
    session.update((project) => ({ ...project, title: "not yet saved" }));
    saved = session.save();
    operation = kind === "switch" ? session.switchProject(switchProject).catch(() => undefined) : result.current.undo();
  });
  await act(async () => {
    await Promise.resolve();
  });
  expect(switchProject).not.toHaveBeenCalled();
  expect(mocks.changeHistory).not.toHaveBeenCalled();
  await act(async () => {
    saving.reject(new Error("disk full"));
    expect(await saved).toBe(false);
    await operation;
  });
  expect(switchProject).not.toHaveBeenCalled();
  expect(mocks.changeHistory).not.toHaveBeenCalled();
  expect(session.savedProject()?.title).toBe("not yet saved");
});

it("finishes preceding saves, switches generation, and ignores a delayed old response", async () => {
  const { session } = setup();
  const old = session.capture();
  const saving = deferred<{ revision: number }>();
  mocks.patchProjectMetadata.mockReturnValueOnce(saving.promise);
  const incoming = { ...session.savedProject()!, id: "new-project", title: "new" };
  const open = vi.fn(async () => incoming);
  let operation!: Promise<unknown>;
  act(() => {
    void session.save();
    operation = session.switchProject(open);
  });
  await act(async () => {
    saving.resolve({ revision: old.base!.revision + 1 });
    await operation;
  });
  expect(open).toHaveBeenCalledOnce();
  expect(session.savedProject()?.id).toBe("new-project");
  expect(session.applyServer(old, old.base!)).toBe(false);
});

it("does not restore unrelated state when optimistic candidate deletion fails", async () => {
  const { session } = setup();
  const response = deferred<StudioProject>(),
    started = deferred<void>();
  mocks.clearCandidates.mockImplementation(() => {
    started.resolve();
    return response.promise;
  });
  let operation!: Promise<unknown>;
  act(() => {
    operation = clearCandidateState(session).catch(() => undefined);
  });
  await act(() => started.promise);
  act(() => {
    session.draftLine(line(session.savedProject()!).id, { text: "入力" });
    session.update((project) => ({ ...project, title: "edited during deletion" }));
  });
  await act(async () => {
    response.reject(new Error("delete failed"));
    await operation;
  });
  expect(session.savedProject()?.title).toBe("edited during deletion");
  expect(line(session.projectRef.current!).text).toBe("入力");
});

it("preserves edits during Undo and invalidates responses from before restoration", async () => {
  const { session, result } = setup();
  const before = session.capture();
  const response = deferred<StudioProject>();
  mocks.project.mockReturnValueOnce(response.promise);
  let undo!: Promise<void>, saved!: Promise<boolean>;
  act(() => {
    undo = result.current.undo();
  });
  await act(async () => {
    await Promise.resolve();
  });
  act(() => {
    session.update((project) => ({ ...project, title: "edited during Undo" }));
    session.draftLine(line(before.base!).id, { text: "変換中" });
    saved = session.save();
  });
  const restored = structuredClone(before.base!);
  restored.scenes[0].title = "restored scene";
  await act(async () => {
    response.resolve(restored);
    await undo;
    expect(await saved).toBe(true);
  });
  expect(session.savedProject()?.title).toBe("edited during Undo");
  expect(session.savedProject()?.scenes[0].title).toBe("restored scene");
  expect(line(session.projectRef.current!).text).toBe("変換中");
  expect(session.applyServer(before, before.base!)).toBe(false);
  expect(mocks.patchProjectMetadata).toHaveBeenCalledWith(restored.revision, { title: "edited during Undo" });
});

it("uses the restored project revision as the save base after Undo", async () => {
  const { session, result, notice } = setup();
  const initial = structuredClone(session.savedProject()!);
  act(() => session.update((current) => ({ ...current, title: "changed" })));
  await act(async () => {
    expect(await session.save()).toBe(true);
  });
  expect(session.serverRevision).toBe(12);

  mocks.project.mockResolvedValueOnce(initial);
  await act(async () => result.current.undo());
  expect(session.savedProject()?.revision).toBe(initial.revision);
  expect(result.current.confirmedProject.current?.revision).toBe(initial.revision);

  mocks.patchProjectMetadata.mockResolvedValueOnce({ revision: initial.revision + 1 });
  act(() => session.update((current) => ({ ...current, title: "edited after Undo" })));
  await act(async () => {
    expect(await session.save()).toBe(true);
  });
  expect(mocks.patchProjectMetadata).toHaveBeenLastCalledWith(initial.revision, { title: "edited after Undo" });
  expect(notice).not.toHaveBeenCalledWith(expect.stringContaining("同じ項目が別の変更でも更新されました"));
});

function SessionEditor({ ready }: { ready: (session: ProjectEditSession) => void }) {
  const { project, editSession } = useProjectEditSession(() => {});
  useEffect(() => {
    editSession.replace(structuredClone(fixture) as StudioProject);
    ready(editSession);
  }, [editSession, ready]);
  if (!project) return null;
  const target = line(project);
  return <EmojiTextArea value={target.text} pronunciations={target.pronunciations} onTextFocus={() => {}} onCommit={() => editSession.commitLine(target.id)} onChange={(text, pronunciations) => editSession.updateLine(target.id, { text, pronunciations })} />;
}

it("keeps an active IME composition through a generation response until explicit commit", () => {
  let session!: ProjectEditSession;
  render(
    <SessionEditor
      ready={(owner) => {
        session = owner;
      }}
    />,
  );
  const operation = session.capture();
  const editor = screen.getByRole("textbox");
  fireEvent.compositionStart(editor);
  editor.textContent = "にほんご";
  fireEvent.input(editor);
  const generated = structuredClone(operation.base!);
  line(generated).takes.push({ ...line(generated).takes[0], id: "generated-during-ime" });
  act(() => {
    session.applyServer(operation, generated);
  });
  expect(screen.getByRole("textbox")).toBe(editor);
  expect(editor.textContent).toBe("にほんご");
  editor.textContent = "日本語";
  fireEvent.compositionEnd(editor);
  expect(line(session.projectRef.current!).text).toBe("日本語");
  expect(line(session.savedProject()!).text).toBe(line(operation.base!).text);
  fireEvent.blur(screen.getByRole("textbox"));
  expect(line(session.savedProject()!).text).toBe("日本語");
  expect(line(session.savedProject()!).takes.at(-1)?.id).toBe("generated-during-ime");
});

it("does not rerender project consumers for row-local keystrokes", () => {
  let session!: ProjectEditSession;
  let renders = 0;
  function ProjectConsumer({ ready }: { ready: (value: ProjectEditSession) => void }) {
    const current = useProjectEditSession(() => {});
    useEffect(() => {
      ready(current.editSession);
    }, [current.editSession, ready]);
    return <span>{current.project?.title}</span>;
  }
  render(
    <Profiler id="project" onRender={() => (renders += 1)}>
      <ProjectConsumer
        ready={(value) => {
          session = value;
        }}
      />
    </Profiler>,
  );
  act(() => session.replace(structuredClone(fixture) as StudioProject));
  const before = renders;
  act(() => {
    session.draftLine(line(session.savedProject()!).id, { text: "一" });
    session.draftLine(line(session.savedProject()!).id, { text: "入力途中" });
  });
  expect(renders).toBe(before);
  expect(line(session.projectRef.current!).text).toBe("入力途中");
});
