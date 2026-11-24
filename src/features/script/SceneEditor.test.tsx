// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SceneTitleInput } from "./SceneEditor";

describe("SceneTitleInput", () => {
  it("commits one final title after editing instead of every keystroke", () => {
    const onCommit = vi.fn();
    render(<SceneTitleInput sceneId="scene-1" title="駅前" onCommit={onCommit} />);

    const input = screen.getByRole("textbox", { name: "シーンタイトル" });
    fireEvent.change(input, { target: { value: "駅" } });
    fireEvent.change(input, { target: { value: "駅前広場" } });
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledOnce();
    expect(onCommit).toHaveBeenCalledWith("scene-1", { title: "駅前広場" });
  });

  it("cancels title editing with Escape", () => {
    const onCommit = vi.fn();
    render(<SceneTitleInput sceneId="scene-1" title="駅前" onCommit={onCommit} />);
    const input = screen.getByRole("textbox", { name: "シーンタイトル" });
    fireEvent.change(input, { target: { value: "変更中" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveValue("駅前");
    expect(onCommit).not.toHaveBeenCalled();
  });
});
