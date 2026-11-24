import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DictionaryScopeCell } from "./DictionaryScopeCell";
import type { PronunciationDictionaryEntry } from "../../types";

const entry: PronunciationDictionaryEntry = {
  id: "global",
  term: "東京",
  reading: "とうきょう",
  source: "manual",
  sourceKeys: ["manual"],
  suggestedReading: "",
  userEdited: true,
  locked: false,
  scopes: ["global"],
  globalId: "global",
  projectId: null,
  merged: false,
  hasDifferentVersion: false,
};

describe("DictionaryScopeCell", () => {
  it("exposes stable pressed toggles for SCENA and PROJECT", () => {
    const toggle = vi.fn().mockResolvedValue(undefined);
    render(<DictionaryScopeCell entry={entry} onToggle={toggle} />);
    expect(screen.getByRole("button", { name: "SCENA" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "PROJECT" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "PROJECT" }));
    expect(toggle).toHaveBeenCalledWith("project", true);
  });
});
