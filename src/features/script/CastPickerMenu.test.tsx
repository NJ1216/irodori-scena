// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CastPickerMenu } from "./CastPickerMenu";

const characters = [
  { id: "a", name: "彩", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 1 },
  { id: "b", name: "蓮", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 2 },
];

describe("CastPickerMenu", () => {
  it("shares option behavior while preserving contextual presentation", async () => {
    const onChoose = vi.fn();
    render(<CastPickerMenu characters={characters} label="キャストを選択" selectedId="a" align="right" density="compact" onChoose={onChoose} />);

    expect(screen.getByRole("listbox", { name: "キャストを選択" })).toHaveClass("is-right", "is-compact");
    expect(screen.getByRole("option", { name: "彩" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("option", { name: "蓮" })).toHaveAttribute("aria-selected", "false");

    await userEvent.click(screen.getByRole("option", { name: "蓮" }));
    expect(onChoose).toHaveBeenCalledWith("b");
  });
});
