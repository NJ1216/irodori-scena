import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ScriptCfgControls } from "./ScriptCfgControls";

const settings: StudioProject["settings"] = {
  speechRate: 1.2,
  steps: 16,
  textCfg: 3,
  voiceCfg: 5,
  captionCfg: 3,
  seed: 0,
  quality: "fast",
  lineGap: 0.7,
  llmBaseUrl: "",
  llmModel: "",
};

describe("ScriptCfgControls", () => {
  it("starts folded and updates each project CFG value independently", () => {
    const onSettings = vi.fn();
    const { container } = render(<ScriptCfgControls settings={settings} onSettings={onSettings} />);
    const details = container.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByLabelText("CFG設定を開閉")).toBeInTheDocument();
    expect(screen.queryByText("CFG設定")).not.toBeInTheDocument();
    expect(screen.getByText("textCfg")).toBeInTheDocument();
    expect(screen.getByText("voiceCfg")).toBeInTheDocument();
    expect(screen.getByText("captionCfg")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("セリフへの追従（スライダー）"), { target: { value: "4.2" } });
    fireEvent.change(screen.getByLabelText("基準ボイスへの追従（スライダー）"), { target: { value: "6.3" } });
    fireEvent.change(screen.getByLabelText("声の指定への追従（スライダー）"), { target: { value: "7.4" } });

    expect(onSettings.mock.calls).toEqual([[{ textCfg: 4.2 }], [{ voiceCfg: 6.3 }], [{ captionCfg: 7.4 }]]);
  });
});
