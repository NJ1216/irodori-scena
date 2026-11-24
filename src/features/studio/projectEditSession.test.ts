import { describe, expect, it, vi } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";

function session() {
  const publish = vi.fn();
  const owner = new ProjectEditSession(publish);
  owner.replace(structuredClone(fixture) as StudioProject);
  return { owner, publish, lineId: fixture.scenes[0].lines[0].id };
}
const firstLine = (project: StudioProject | null) => project!.scenes[0].lines[0];

describe("project edit ownership", () => {
  it("keeps same-render drafts out of a later scene save", () => {
    const { owner, lineId, publish } = session();
    owner.updateLine(lineId, { text: "入力途中", pronunciations: [] });
    expect(publish).toHaveBeenCalledTimes(1);
    owner.update((project) => ({ ...project, scenes: project.scenes.map((scene) => ({ ...scene, title: "変更" })) }));
    expect(firstLine(owner.projectRef.current).text).toBe("入力途中");
    expect(firstLine(owner.savedProject()).text).toBe(fixture.scenes[0].lines[0].text);
    expect(owner.savedProject()!.scenes[0].title).toBe("変更");
    expect(firstLine(publish.mock.lastCall?.[0] as StudioProject).text).toBe(fixture.scenes[0].lines[0].text);
    owner.commitLine(lineId);
    expect(firstLine(owner.savedProject()).text).toBe("入力途中");
  });

  it.each(["", "-", "0.", "にほんご変換中"])('retains draft "%s" when a generation finishes', (text) => {
    const { owner, lineId } = session();
    const operation = owner.capture();
    owner.updateLine(lineId, { text });
    const server = structuredClone(operation.base!);
    firstLine(server).takes.push({ ...firstLine(server).takes[0], id: "new-take" });
    firstLine(server).selectedTakeId = "new-take";
    owner.applyServer(operation, server);
    expect(firstLine(owner.projectRef.current).text).toBe(text);
    expect(firstLine(owner.projectRef.current).selectedTakeId).toBe("new-take");
    expect(firstLine(owner.savedProject()).text).toBe(firstLine(operation.base).text);
  });

  it("preserves committed edits, line readings, and selected take changed after the request", () => {
    const { owner, lineId } = session();
    const operation = owner.capture();
    owner.updateLine(lineId, { text: "日本語", pronunciations: [{ id: "reading-1", text: "日本語", start: 0, end: 3, reading: "にほんご" }] });
    owner.commitLine(lineId);
    owner.updateLine(lineId, { selectedTakeId: "user-choice" });
    const server = structuredClone(operation.base!);
    firstLine(server).takes.push({ ...firstLine(server).takes[0], id: "generated" });
    firstLine(server).selectedTakeId = "generated";
    server.revision = 8;
    owner.applyServer(operation, server);
    expect(firstLine(owner.savedProject())).toMatchObject({ text: "日本語", pronunciations: [{ id: "reading-1", text: "日本語", start: 0, end: 3, reading: "にほんご" }], selectedTakeId: "user-choice" });
    expect(firstLine(owner.savedProject()).takes.at(-1)?.id).toBe("generated");
    expect(owner.serverRevision).toBe(8);
  });

  it("adopts a generated take revision and rebases a concurrent pending save", () => {
    const { owner, lineId } = session();
    const rebasePending = vi.fn();
    owner.persistence = { save: vi.fn(), wait: async () => true, pause: vi.fn(), resume: vi.fn(), rebasePending };
    const operation = owner.capture();
    owner.update((project) => ({ ...project, title: "生成中の編集" }));
    owner.applyServerUpdate(operation, (project) => {
      const generated = structuredClone(project);
      firstLine(generated).takes.push({ ...firstLine(generated).takes[0], id: "generated" });
      generated.revision = 9;
      return generated;
    });
    expect(owner.savedProject()?.title).toBe("生成中の編集");
    expect(firstLine(owner.savedProject()).takes.at(-1)?.id).toBe("generated");
    expect(owner.savedProject()?.revision).toBe(9);
    expect(rebasePending).toHaveBeenLastCalledWith(owner.savedProject());
    expect(lineId).toBe(firstLine(owner.savedProject()).id);
  });

  it("rejects responses from another project and an earlier visit to the same project", () => {
    const { owner } = session();
    const operation = owner.capture();
    owner.replace({ ...operation.base!, id: "other" });
    expect(owner.applyServer(operation, operation.base!)).toBe(false);
    owner.replace({ ...operation.base!, title: "reopened" });
    expect(owner.applyServer(operation, operation.base!)).toBe(false);
    expect(owner.savedProject()!.title).toBe("reopened");
  });

  it("rolls back only optimistic candidate removal after a concurrent edit", () => {
    const { owner, lineId } = session();
    const before = owner.savedProject()!;
    owner.update((project) => ({ ...project, candidates: [] }));
    const optimistic = owner.capture();
    owner.updateLine(lineId, { text: "編集中" });
    owner.update((project) => ({ ...project, title: "新題" }));
    owner.applyServer(optimistic, before);
    expect(owner.savedProject()!.title).toBe("新題");
    expect(firstLine(owner.projectRef.current).text).toBe("編集中");
  });
});
