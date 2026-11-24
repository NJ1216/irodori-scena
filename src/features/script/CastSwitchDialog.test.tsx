import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { CastSwitchDialog } from "./CastSwitchDialog";

const project = {
  characters: [
    { id: "cast-a", name: "彩", avatarUrl: "/media/aya.png" },
    { id: "cast-b", name: "凛", avatarUrl: "/media/rin.png" },
  ],
  scenes: [{ id: "scene-1", lines: [{ id: "line-1", characterId: "cast-a" }] }],
} as StudioProject;

it("uses the thumbnail character picker and applies its mapping", async () => {
  const onApply = vi.fn().mockResolvedValue(undefined);
  render(<CastSwitchDialog project={project} busy={false} onClose={vi.fn()} onApply={onApply} />);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "彩の切り替え先：彩" }));
  const menu = screen.getByRole("listbox", { name: "彩の切り替え先" });
  expect(menu.parentElement).toBe(document.body);
  expect(menu).toHaveClass("is-portal");
  expect(menu.querySelectorAll(".cast-picker-option-avatar img")).toHaveLength(2);
  await userEvent.click(screen.getByRole("option", { name: "凛" }));
  await userEvent.click(screen.getByRole("button", { name: "同時に切り替える" }));
  expect(onApply).toHaveBeenCalledWith([{ fromCharacterId: "cast-a", toCharacterId: "cast-b" }]);
});
