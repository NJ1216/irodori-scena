import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CharacterImagePromptEditor } from "./CharacterImagePromptEditor";

describe("character image prompt editor", () => {
  it("explains that SCENA creates prompt text but does not generate images", () => {
    render(<CharacterImagePromptEditor model={{ editImagePrompt: "", setEditImagePrompt: vi.fn(), setImagePromptSuggestionOpen: vi.fn() } as never} />);
    const button = screen.getByRole("button", { name: "画像生成用プロンプト文を作る" });
    expect(button).toHaveAttribute("title", expect.stringContaining("SCENAには画像生成機能はありません"));
  });
});
