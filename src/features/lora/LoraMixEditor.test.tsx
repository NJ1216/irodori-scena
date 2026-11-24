import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { LoraMix } from "../../types/project";
import { LoraMixEditor } from "./LoraMixEditor";
const initial: LoraMix = { version: 1, baseWeight: 5000, entries: [{ assetId: "one", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev", weight: 5000 }] };
function Editor() {
  const [value, setValue] = useState(initial);
  return (
    <form>
      <LoraMixEditor value={value} names={["ベース", "長いLoRAの名前"]} onChange={setValue} />
      <output data-testid="mix">{JSON.stringify(value)}</output>
    </form>
  );
}
it("labels below the segments and keeps percentages read-only until editing", () => {
  render(<Editor />);
  expect(screen.getByText("Base")).toBeVisible();
  expect(screen.getByText("長いLoRAの名前")).toBeVisible();
  expect(screen.getAllByText("50%")).toHaveLength(2);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /リセット|ベース100%/ })).not.toBeInTheDocument();
  expect(screen.getByTitle("長いLoRAの名前 50%")).toBeInTheDocument();
});
it("supports fine increments, shift, and keyboard endpoints at ten percent", () => {
  render(<Editor />);
  const boundary = screen.getByRole("slider");
  fireEvent.keyDown(boundary, { key: "ArrowLeft" });
  expect(boundary).toHaveAttribute("aria-valuenow", "49.99");
  fireEvent.keyDown(boundary, { key: "ArrowRight", shiftKey: true });
  expect(boundary).toHaveAttribute("aria-valuenow", "50.99");
  fireEvent.keyDown(boundary, { key: "Home" });
  expect(boundary).toHaveAttribute("aria-valuenow", "10");
  expect(screen.getByText("90%")).toBeVisible();
  fireEvent.keyDown(boundary, { key: "End" });
  expect(boundary).toHaveAttribute("aria-valuenow", "90");
  expect(screen.getByText("10%")).toBeVisible();
  expect(boundary).toHaveAttribute("aria-valuemin", "10");
  expect(boundary).toHaveAttribute("aria-valuemax", "90");
});
it("drag clamps at ten percent while preserving all labeled segments", () => {
  const change = vi.fn();
  render(<LoraMixEditor value={initial} names={["ベース", "LoRA"]} onChange={change} />);
  const boundary = screen.getByRole("slider");
  boundary.setPointerCapture = vi.fn();
  vi.spyOn(boundary.parentElement!, "getBoundingClientRect").mockReturnValue({ width: 100 } as DOMRect);
  fireEvent(boundary, new MouseEvent("pointerdown", { bubbles: true, clientX: 50 }));
  fireEvent(boundary, new MouseEvent("pointermove", { bubbles: true, clientX: 500 }));
  fireEvent(boundary, new MouseEvent("pointerup", { bubbles: true }));
  expect(change).toHaveBeenLastCalledWith({ ...initial, baseWeight: 9000, entries: [{ ...initial.entries[0], weight: 1000 }] });
});

it("specifies a percentage from the context menu, preserves invalid drafts, and removes only the mix entry", () => {
  render(<Editor />);
  fireEvent.contextMenu(screen.getByTitle("長いLoRAの名前 50%"));
  fireEvent.click(screen.getByRole("menuitem", { name: "割合を指定…" }));
  const input = screen.getByLabelText("割合（%）");
  fireEvent.change(input, { target: { value: "-" } });
  fireEvent.click(screen.getByRole("button", { name: "適用" }));
  expect(input).toHaveValue("-");
  expect(screen.getByRole("alert")).toBeVisible();
  fireEvent.change(input, { target: { value: "75.25" } });
  fireEvent.click(screen.getByRole("button", { name: "適用" }));
  expect(screen.getByText("24.75%")).toBeVisible();
  fireEvent.contextMenu(screen.getByTitle("長いLoRAの名前 75.25%"));
  fireEvent.click(screen.getByRole("menuitem", { name: "削除" }));
  expect(screen.getByText("100%")).toBeVisible();
});

it("double-click edits inline, commits on Enter without submitting, and preserves invalid drafts", () => {
  render(<Editor />);
  fireEvent.doubleClick(screen.getByRole("button", { name: "長いLoRAの名前の割合 50%" }));
  const input = screen.getByRole("textbox", { name: "長いLoRAの名前の割合（%）" });
  fireEvent.change(input, { target: { value: "-" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input).toHaveValue("-");
  expect(input).toBeInvalid();
  expect(screen.getByRole("alert")).toBeVisible();
  fireEvent.change(input, { target: { value: "75.25" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getByText("24.75%")).toBeVisible();
  expect(screen.getByText("75.25%")).toBeVisible();
});
it("commits on blur and cancels with Escape while retaining the last valid mix", () => {
  render(<Editor />);
  fireEvent.doubleClick(screen.getByRole("button", { name: "ベースの割合 50%" }));
  const input = screen.getByRole("textbox", { name: "ベースの割合（%）" });
  fireEvent.change(input, { target: { value: "60" } });
  fireEvent.blur(input);
  expect(screen.getByText("40%")).toBeVisible();
  const base = screen.getByRole("button", { name: "ベースの割合 60%" });
  fireEvent.keyDown(base, { key: "F2" });
  const next = screen.getByRole("textbox", { name: "ベースの割合（%）" });
  fireEvent.change(next, { target: { value: "2" } });
  fireEvent.blur(next);
  expect(next).toHaveValue("2");
  expect(next).toBeInvalid();
  fireEvent.keyDown(next, { key: "Escape" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText("60%")).toBeVisible();
  expect(screen.getByText("40%")).toBeVisible();
});
