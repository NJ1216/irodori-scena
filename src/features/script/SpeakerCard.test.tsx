import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { SpeakerCard } from "./SpeakerCard";
import { ScriptCastContextDialog } from "./ScriptCastContextDialog";

const character = { id: "cast-a", name: "彩", referenceAudioUrl: "" } as Character;

describe("script cast role presentation", () => {
  it.each(["登場人物", " 彩 ", "彩", "　登場人物　", "", "  "])("hides redundant role %j without changing its value", (role) => {
    const context = Object.freeze({ role, description: "穏やかな人物です。" });
    const { container } = render(<SpeakerCard character={character} scriptContext={context} onPlay={vi.fn()} />);
    expect(container.querySelector(".script-cast-role")).toBeNull();
    expect(screen.getByText("穏やかな人物です。")).toBeInTheDocument();
    expect(context.role).toBe(role);
  });

  it.each(["店員", "相談する側", "彩の友人", "登場人物を案内する係"])("keeps meaningful role %j", (role) => {
    render(<SpeakerCard character={character} scriptContext={{ role, description: "紹介" }} onPlay={vi.fn()} />);
    expect(screen.getByText(role)).toHaveClass("script-cast-role");
  });

  it.each(["登場人物", "彩"])("keeps hidden role %j visible and saveable in the editor", async (role) => {
    const save = vi.fn();
    render(<ScriptCastContextDialog character={character} context={{ role, description: "紹介" }} onClose={vi.fn()} onSave={save} />);
    expect(screen.getByRole("textbox", { name: "役割" })).toHaveValue(role);
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(save).toHaveBeenCalledWith({ role, description: "紹介" });
  });

  it("shows the cast thumbnail in the script context editor", () => {
    render(<ScriptCastContextDialog character={{ ...character, avatarUrl: "/media/aya.png" }} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "台本上のキャスト設定" }).querySelector(".script-cast-context-avatar img")).toBeInTheDocument();
  });

  it("switches the reference button to stop while that cast plays", async () => {
    const onPlay = vi.fn();
    const { rerender } = render(<SpeakerCard character={character} onPlay={onPlay} onEditScriptContext={vi.fn()} />);
    const play = screen.getByRole("button", { name: "参照ボイスを再生" });
    expect(play).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(play);
    expect(onPlay).toHaveBeenCalledWith(character);

    rerender(<SpeakerCard character={character} onPlay={onPlay} onEditScriptContext={vi.fn()} playingReference />);
    const stop = screen.getByRole("button", { name: "参照ボイスを停止" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    expect(stop).toHaveTextContent("■");
    await userEvent.click(stop);
    expect(onPlay).toHaveBeenCalledTimes(2);
  });
});
