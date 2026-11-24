import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CharacterImagePromptSuggestionDialog, PromptMultiSelect } from "./CharacterImagePromptSuggestionDialog";

function Harness() {
  const [value, setValue] = useState<string[]>([]);
  return <PromptMultiSelect label="アクセサリー" value={value} groups={[{ label: "頭・髪", options: ["ティアラ", "王冠"] }]} onChange={setValue} />;
}

describe("image prompt multiple selection", () => {
  it("keeps the menu open while selecting multiple values and can clear them", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: /アクセサリー/ });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: /頭・髪/ }));
    await user.click(screen.getByRole("checkbox", { name: "ティアラ" }));
    await user.click(screen.getByRole("checkbox", { name: "王冠" }));
    expect(screen.getByRole("checkbox", { name: "ティアラ" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "王冠" })).toBeChecked();
    expect(trigger).toHaveTextContent("ティアラ、王冠");
    await user.click(screen.getByRole("button", { name: /選択を解除/ }));
    expect(trigger).toHaveTextContent("指定無し");
    expect(trigger).toHaveClass("is-empty");
    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("shows numeric ages and occupation submenus without a makeup field", async () => {
    const user = userEvent.setup();
    const setOccupation = vi.fn();
    const setCameraAngle = vi.fn();
    const setComposition = vi.fn();
    const setScreenEffect = vi.fn();
    const model = new Proxy(
      {
        imagePromptSuggestionOpen: true,
        editing: { id: "cast-1", name: "彩" },
        editDetails: { gender: "女性" },
        imagePromptGestures: [],
        imagePromptAccessory: [],
        imagePromptFacialHair: [],
        imagePromptFrecklesMoles: [],
        imagePromptScars: [],
        imagePromptTattoos: [],
        imagePromptBackgroundDetails: { color: "", gradientColor1: "", gradientColor2: "", gradientDirection: "" },
        setImagePromptOccupation: setOccupation,
        setImagePromptCameraAngle: setCameraAngle,
        setImagePromptComposition: setComposition,
        setImagePromptScreenEffect: setScreenEffect,
      } as Record<string, unknown>,
      {
        get(target, property: string) {
          if (property in target) return target[property];
          if (property.startsWith("set") || property === "suggestCharacterImagePrompt") return vi.fn();
          return "";
        },
      },
    );
    render(<CharacterImagePromptSuggestionDialog model={model as never} />);
    expect(screen.getByRole("heading", { name: "画像生成用プロンプト文を作る" })).toBeInTheDocument();
    expect(screen.queryByText("メイク")).not.toBeInTheDocument();
    expect(screen.getByText("年齢")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "構図の候補を表示" }));
    await user.click(screen.getByRole("button", { name: /遠近・レンズ/ }));
    const fisheye = screen.getByRole("option", { name: "魚眼レンズで写す" });
    expect(fisheye).toHaveAttribute("title", "魚眼レンズのように画面周辺を湾曲させ、強い広がりを作ります。");
    await user.click(fisheye);
    expect(setComposition).toHaveBeenCalledWith("魚眼レンズで写す");
    await user.click(screen.getByRole("button", { name: "カメラアングルの候補を表示" }));
    await user.click(screen.getByRole("button", { name: /上からの視点/ }));
    const overhead = screen.getByRole("option", { name: "真上から見下ろす" });
    expect(overhead).toHaveAttribute("title", "被写体のほぼ真上から、地面へ向かって見下ろします。");
    await user.click(overhead);
    expect(setCameraAngle).toHaveBeenCalledWith("真上から見下ろす");
    await user.click(screen.getByRole("button", { name: "画面効果・技法の候補を表示" }));
    await user.click(screen.getByRole("button", { name: /動き・強調/ }));
    const motionBlur = screen.getByRole("option", { name: "動きをぼかす" });
    expect(motionBlur).toHaveAttribute("title", "移動方向に像を流してぼかし、素早い動きや速度感を表現します。");
    await user.click(motionBlur);
    expect(setScreenEffect).toHaveBeenCalledWith("動きをぼかす");
    await user.click(screen.getByRole("button", { name: "職業の候補を表示" }));
    expect(screen.getByRole("menu").closest(".modal")).toBeNull();
    await user.click(screen.getByRole("button", { name: /公共・保安/ }));
    await user.click(screen.getByRole("option", { name: "警察官" }));
    expect(setOccupation).toHaveBeenCalledWith("警察官");
  });
});
