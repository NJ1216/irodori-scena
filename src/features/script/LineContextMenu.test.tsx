import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import type { ScriptViewProps } from "./ScriptViewTypes";
import { LineContextMenu } from "./LineContextMenu";

afterEach(() => {
  cleanup();
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

it.each([
  ["MacIntel", "⌘⌥R", "⌘⇧R"],
  ["Win32", "Ctrl+Alt+R", "Ctrl+Shift+R"],
])("shows existing %s shortcuts in the menu", (platform, newTake, replace) => {
  vi.stubGlobal("navigator", { platform });
  const project = { scenes: [{ id: "scene", lines: [{ id: "line", text: "台詞", takes: [], selectedTakeId: null }] }] } as unknown as StudioProject;
  render(<LineContextMenu state={{ sourceId: "line", ids: ["line"], x: 20, y: 20 }} project={project} props={{ busy: null, onNotice: vi.fn() } as unknown as ScriptViewProps} onClose={vi.fn()} />);
  expect(screen.getByRole("menuitem", { name: "新規テイク" }).querySelector("kbd")).toHaveTextContent(newTake);
  expect(screen.getByRole("menuitem", { name: "上書き生成" }).querySelector("kbd")).toHaveTextContent(replace);
  expect(screen.getByRole("menuitem", { name: "削除" }).querySelector("kbd")).toHaveTextContent("Delete");
});

it("keeps both seed actions for a mixed selection and routes each to its own lines", () => {
  const project = {
    scenes: [
      {
        id: "scene",
        lines: [
          { id: "fixed", text: "一", fixedSeed: 42, takes: [], selectedTakeId: null },
          { id: "free", text: "二", takes: [], selectedTakeId: null },
        ],
      },
    ],
  } as unknown as StudioProject;
  const onSetLineSeeds = vi.fn();
  const props = { selectedLineIds: ["fixed", "free"], onSetLineSeeds, onNotice: vi.fn(), busy: null } as unknown as ScriptViewProps;
  const onClose = vi.fn();
  render(<LineContextMenu state={{ sourceId: "fixed", ids: ["fixed", "free"], x: 20, y: 20 }} project={project} props={props} onClose={onClose} />);
  const fix = screen.getByRole("menuitem", { name: "Seedを固定" });
  const release = screen.getByRole("menuitem", { name: "Seed固定を解除" });
  expect(fix).toBeEnabled();
  fireEvent.click(fix);
  expect(onSetLineSeeds).toHaveBeenCalledWith(["free"], { fixedSeed: 42 });
  fireEvent.click(release);
  expect(onSetLineSeeds).toHaveBeenCalledWith(["fixed"], { fixedSeed: undefined, manualSeed: undefined });
});

it("moves through enabled menu items with the keyboard and closes on Escape", () => {
  const project = { scenes: [{ id: "scene", lines: [{ id: "line", text: "台詞", takes: [], selectedTakeId: null }] }] } as unknown as StudioProject;
  const onClose = vi.fn();
  render(<LineContextMenu state={{ sourceId: "line", ids: ["line"], x: 20, y: 20 }} project={project} props={{ busy: null, onNotice: vi.fn() } as unknown as ScriptViewProps} onClose={onClose} />);
  expect(screen.getByRole("menuitem", { name: "新規テイク" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
  expect(screen.getByRole("menuitem", { name: "上書き生成" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
});
