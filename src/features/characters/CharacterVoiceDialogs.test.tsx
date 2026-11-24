// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CandidateChoices } from "./CharacterVoiceDialogs";

it("keeps existing candidates and appends pending slots during additional generation", () => {
  const candidates = Array.from({ length: 5 }, (_, index) => ({
    id: `candidate-${index}`,
    audioUrl: `/candidate-${index}.wav`,
  }));

  render(<CandidateChoices candidates={candidates as never} label="基準" generatingCount={10} onSelect={vi.fn()} onPlay={vi.fn()} onPause={vi.fn()} onEnded={vi.fn()} />);

  for (const choice of ["A", "B", "C", "D", "E"]) expect(screen.getByRole("button", { name: `基準候補 ${choice}を再生` })).toBeEnabled();
  for (const choice of ["F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]) expect(screen.getByRole("button", { name: `基準候補 ${choice}を生成中` })).toBeDisabled();
});
