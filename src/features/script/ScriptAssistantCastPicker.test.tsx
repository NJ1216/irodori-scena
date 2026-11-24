// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ScriptAssistantCastPicker } from "./ScriptAssistantCastPicker";

const characters = [
  { id: "a", name: "彩", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 1 },
  { id: "b", name: "蓮", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 2 },
  { id: "c", name: "凪", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 3 },
];

describe("ScriptAssistantCastPicker", () => {
  it("adds an unselected cast from the compact picker", async () => {
    const onChange = vi.fn();
    render(<ScriptAssistantCastPicker characters={characters} selectedIds={["a"]} requiredIds={[]} busy={false} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "生成対象キャストを追加" }));
    await userEvent.click(screen.getByRole("option", { name: "蓮" }));
    expect(onChange).toHaveBeenCalledWith(["a", "b"]);
  });

  it("prevents removing a required cast or the final remaining cast", () => {
    const { rerender } = render(<ScriptAssistantCastPicker characters={characters} selectedIds={["a", "b"]} requiredIds={["a"]} busy={false} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "彩を生成対象から外す" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "蓮を生成対象から外す" })).toBeEnabled();
    rerender(<ScriptAssistantCastPicker characters={characters} selectedIds={["b"]} requiredIds={[]} busy={false} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "蓮を生成対象から外す" })).toBeDisabled();
  });
});
