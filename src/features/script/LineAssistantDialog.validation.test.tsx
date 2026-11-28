// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "../studio/projectEditSession";
import { LineAssistantDialog } from "./LineAssistantDialog";

const mocks = vi.hoisted(() => ({ startScriptAssistantJob: vi.fn() }));
vi.mock("../../api", () => ({ api: { startScriptAssistantJob: mocks.startScriptAssistantJob, scriptAssistantJob: vi.fn(), cancelScriptAssistantJob: vi.fn(), suggestScriptAssistant: vi.fn(), applyScriptAssistantProposal: vi.fn() } }));

const character = (id: string, name: string) => ({ id, name, profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 1 });
const project = {
  version: 1,
  revision: 0,
  id: "project",
  title: "台本",
  candidates: [],
  characters: [character("a", "彩"), character("b", "蓮")],
  scenes: [
    {
      id: "scene",
      title: "駅前",
      lines: [
        { id: "one", characterId: "a", text: "一行目", stageDirection: "", takes: [], selectedTakeId: null },
        { id: "two", characterId: "b", text: "二行目", stageDirection: "", takes: [], selectedTakeId: null },
      ],
    },
  ],
  settings: { speechRate: 1, steps: 16, textCfg: 1.5, voiceCfg: 2, seed: 1, quality: "fast", llmBaseUrl: "", llmModel: "" },
} satisfies StudioProject;

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});

it("shows a failed input check in the dialog footer instead of the notice overlay", async () => {
  const onNotice = vi.fn();
  const connection = { provider: "ollama" as const, baseUrl: "", model: "", apiKeyEnabled: false, hasApiKey: false, apiKey: "", engineDir: "", engineDirVerified: false };
  const session = new ProjectEditSession(() => {});
  session.replace(project);
  render(<LineAssistantDialog projectSession={session} project={project} connection={connection} connectionReady target={{ kind: "rewrite", lineIds: ["one", "two"] }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={onNotice} />);

  await userEvent.click(screen.getByRole("button", { name: "✦ 提案を生成" }));

  const footer = document.querySelector(".dialog-footer") as HTMLElement;
  expect(footer).toContainElement(screen.getByRole("alert"));
  expect(screen.getByRole("alert")).toHaveTextContent("設定ページで既定のLLMモデルを選択してください。");
  expect(onNotice).not.toHaveBeenCalled();
  expect(mocks.startScriptAssistantJob).not.toHaveBeenCalled();
});
