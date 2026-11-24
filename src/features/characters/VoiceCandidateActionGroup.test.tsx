// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { VoiceCandidateActionGroup } from "./VoiceCandidateActionGroup";

it("invokes generation and exposes an immediate generating state", () => {
  const generate = vi.fn();
  const { rerender } = render(<VoiceCandidateActionGroup label="基準ボイス" onGenerate={generate} />);

  fireEvent.click(screen.getByRole("button", { name: "基準ボイスの候補をつくる" }));
  expect(generate).toHaveBeenCalledOnce();

  rerender(<VoiceCandidateActionGroup label="基準ボイス" disabled generating onGenerate={generate} />);
  expect(screen.getByRole("button", { name: "基準ボイスの候補をつくる" })).toHaveTextContent("生成中…");
});
