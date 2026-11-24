// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { MEANFLOW_MODEL_REPO, MEANFLOW_MODEL_REVISION } from "../shared/ttsSampling";
import { ScriptSpeakerRail } from "./ScriptSpeakerRail";

function project(meanflow: boolean): StudioProject {
  return {
    version: 1,
    revision: 0,
    id: "project",
    title: "test",
    characters: [],
    candidates: [],
    scenes: [],
    settings: { speechRate: 1.2, steps: 16, textCfg: 3, voiceCfg: 5, captionCfg: 3, seed: 0, quality: "fast", llmBaseUrl: "", llmModel: "" },
    ...(meanflow ? { ttsSelection: { engine: { repo: "Aratako/Irodori-TTS", commit: "89f9d8fbd4d51ea019867ee1197725ede1df13c5", externalId: null }, model: { repo: MEANFLOW_MODEL_REPO, revision: MEANFLOW_MODEL_REVISION }, codecRevision: "codec", optimizationProfile: "upstream-meanflow" } } : {}),
  };
}

function renderRail(meanflow: boolean) {
  render(<ScriptSpeakerRail project={project(meanflow)} onPlayReference={vi.fn()} playingReferenceCharacterId={null} onSettings={vi.fn()} onEditScriptContext={vi.fn()} onOpenCastSwitch={vi.fn()} />);
}

describe("ScriptSpeakerRail sampling controls", () => {
  it("keeps RF quality presets and CFG controls", () => {
    renderRail(false);
    expect(screen.getByRole("button", { name: /バランス/ })).toBeInTheDocument();
    expect(screen.getByLabelText("CFG設定を開閉")).toBeInTheDocument();
  });

  it("hides unsupported MF presets and CFG while retaining common controls", () => {
    renderRail(true);
    expect(screen.queryByRole("button", { name: /バランス/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("CFG設定を開閉")).not.toBeInTheDocument();
    expect(screen.getByLabelText("共通の話速（スライダー）")).toBeInTheDocument();
  });
});
