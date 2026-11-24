import { beforeEach, expect, it, vi } from "vitest";
import type { Character, StudioProject } from "../../types";
import { api } from "../../api";
import { confirmDestructiveAction } from "../shared/destructiveConfirmation";
import { deleteCharacter } from "./deleteCharacter";
import { ProjectEditSession } from "./projectEditSession";

vi.mock("../../api", () => ({ api: { deleteCharacter: vi.fn() } }));
vi.mock("../shared/destructiveConfirmation", () => ({ confirmDestructiveAction: vi.fn() }));
const cast = { id: "one", name: "彩" } as Character;
beforeEach(() => vi.clearAllMocks());

function model() {
  const editSession = new ProjectEditSession(vi.fn());
  editSession.replace({ id: "project", characters: [cast], scenes: [] } as unknown as StudioProject);
  return { editSession, setBusy: vi.fn(), setNotice: vi.fn() };
}

it("returns false until the existing destructive confirmation has been completed", async () => {
  vi.mocked(confirmDestructiveAction).mockReturnValue(false);
  const prepare = vi.fn();
  await expect(deleteCharacter(model(), cast, prepare)).resolves.toBe(false);
  expect(prepare).not.toHaveBeenCalled();
  expect(api.deleteCharacter).not.toHaveBeenCalled();
});

it("does not delete a cast when particle preparation fails", async () => {
  vi.mocked(confirmDestructiveAction).mockReturnValue(true);
  vi.mocked(api.deleteCharacter).mockResolvedValue({ id: "project", characters: [], scenes: [] } as unknown as StudioProject);
  const prepare = vi.fn(async () => {
    expect(api.deleteCharacter).not.toHaveBeenCalled();
    throw new Error("particle image failed");
  });
  const owner = model();
  await expect(deleteCharacter(owner, cast, prepare)).resolves.toBe(false);
  expect(prepare).toHaveBeenCalledOnce();
  expect(api.deleteCharacter).not.toHaveBeenCalled();
  expect(owner.setNotice).toHaveBeenCalledWith(expect.stringContaining("particle image failed"));
});

it("does not send a deletion to a project switched during capture", async () => {
  vi.mocked(confirmDestructiveAction).mockReturnValue(true);
  const owner = model();
  await expect(
    deleteCharacter(owner, cast, async () => {
      owner.editSession.replace({ id: "another", characters: [cast], scenes: [] } as unknown as StudioProject);
    }),
  ).resolves.toBe(false);
  expect(api.deleteCharacter).not.toHaveBeenCalled();
});

it("signals success only after the server project has been applied", async () => {
  const owner = model();
  vi.mocked(confirmDestructiveAction).mockReturnValue(true);
  vi.mocked(api.deleteCharacter).mockResolvedValue({ id: "project", characters: [], scenes: [] } as unknown as StudioProject);
  await expect(deleteCharacter(owner, cast)).resolves.toBe(true);
  expect(owner.editSession.projectRef.current?.characters).toEqual([]);
  expect(owner.setNotice).toHaveBeenCalledWith(expect.stringContaining("「彩」を削除しました"));
});

it("returns false and preserves the cast when deletion fails", async () => {
  const owner = model();
  vi.mocked(confirmDestructiveAction).mockReturnValue(true);
  vi.mocked(api.deleteCharacter).mockRejectedValue(new Error("network"));
  await expect(deleteCharacter(owner, cast)).resolves.toBe(false);
  expect(owner.editSession.projectRef.current?.characters).toEqual([cast]);
  expect(owner.setNotice).toHaveBeenCalledWith(expect.stringContaining("削除できませんでした"));
});
