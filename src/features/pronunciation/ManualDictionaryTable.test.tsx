import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PronunciationDictionaryEntry } from "../../types";
import { ManualDictionaryTable } from "./ManualDictionaryTable";

const entry = (scope: "global" | "project", reading = "とうきょう"): PronunciationDictionaryEntry => ({
  id: scope,
  term: "Tokyo",
  reading,
  source: "manual",
  sourceKeys: ["manual"],
  suggestedReading: reading,
  userEdited: true,
  locked: false,
  scopes: [scope],
  globalId: scope === "global" ? scope : null,
  projectId: scope === "project" ? scope : null,
});

function setup(entries: PronunciationDictionaryEntry[] = []) {
  const onAdd = vi.fn().mockResolvedValue(undefined);
  render(<ManualDictionaryTable entries={entries} castTerms={new Set()} suggestReadings={false} llmBusy={false} suggestedIds={new Set()} addRequest={1} onRequestAdd={vi.fn()} onSuggest={vi.fn()} onSave={vi.fn()} onLockChange={vi.fn()} onAdd={onAdd} onToggleScope={vi.fn()} onNotice={vi.fn()} />);
  return onAdd;
}

describe("ManualDictionaryTable new row", () => {
  it("starts with both destinations and submits them once", async () => {
    const onAdd = setup();
    expect(screen.getByRole("button", { name: "SCENA" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "PROJECT" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("新しい語句"), { target: { value: "Tokyo" } });
    fireEvent.blur(screen.getByLabelText("新しい読み"), { relatedTarget: null });
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith("Tokyo", "", ["global", "project"]));
  });

  it("disables occupied destinations and restores availability while preserving manual choices", () => {
    setup([entry("global")]);
    const term = screen.getByLabelText("新しい語句");
    const destination = within(screen.getByLabelText("新規項目の保存先"));
    const scena = destination.getByRole("button", { name: "SCENA" });
    const project = destination.getByRole("button", { name: "PROJECT" });
    fireEvent.click(project);
    fireEvent.change(term, { target: { value: "  tOkYo " } });
    expect(scena).toBeDisabled();
    expect(project).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("SCENAには登録済みです。PROJECT用の読みを追加します。")).toBeInTheDocument();
    fireEvent.change(term, { target: { value: "Osaka" } });
    expect(scena).not.toBeDisabled();
    expect(scena).toHaveAttribute("aria-pressed", "true");
    expect(project).toHaveAttribute("aria-pressed", "false");
  });

  it("blocks a third reading when both destinations are occupied", async () => {
    const onAdd = setup([entry("global"), entry("project", "とーきょー")]);
    fireEvent.change(screen.getByLabelText("新しい語句"), { target: { value: "Tokyo" } });
    const destination = within(screen.getByLabelText("新規項目の保存先"));
    expect(destination.getByRole("button", { name: "SCENA" })).toBeDisabled();
    expect(destination.getByRole("button", { name: "PROJECT" })).toBeDisabled();
    fireEvent.blur(screen.getByLabelText("新しい読み"), { relatedTarget: null });
    expect(await screen.findByRole("alert")).toHaveTextContent("既存行を編集してください");
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("describes the save destinations from the shared tooltip", () => {
    setup();
    fireEvent.focus(screen.getByLabelText("保存先の説明"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("PROJECTがオフでも");
  });
});
