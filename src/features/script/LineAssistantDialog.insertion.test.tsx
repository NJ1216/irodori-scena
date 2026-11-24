// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "../studio/projectEditSession";
import { LineAssistantDialog } from "./LineAssistantDialog";

const mocks = vi.hoisted(() => ({
  saveProject: vi.fn(),
  startScriptAssistantJob: vi.fn(),
  scriptAssistantJob: vi.fn(),
  cancelScriptAssistantJob: vi.fn(),
  suggestScriptAssistant: vi.fn(),
}));
vi.mock("../../api", () => ({
  api: {
    saveProject: mocks.saveProject,
    startScriptAssistantJob: mocks.startScriptAssistantJob,
    scriptAssistantJob: mocks.scriptAssistantJob,
    cancelScriptAssistantJob: mocks.cancelScriptAssistantJob,
    suggestScriptAssistant: mocks.suggestScriptAssistant,
    applyScriptAssistantProposal: vi.fn(),
  },
}));

const character = (id: string, name: string) => ({
  id,
  name,
  profile: "",
  voiceKeywords: "",
  referenceAudioUrl: "",
  referenceFile: "",
  createdAt: 1,
});
const project = {
  version: 1,
  revision: 0,
  id: "project",
  title: "台本",
  candidates: [],
  characters: [character("a", "彩"), character("b", "蓮"), character("c", "凪")],
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
  settings: {
    speechRate: 1,
    steps: 16,
    textCfg: 1.5,
    voiceCfg: 2,
    seed: 1,
    quality: "fast",
    llmBaseUrl: "",
    llmModel: "",
  },
} satisfies StudioProject;

const connection = { provider: "ollama" as const, baseUrl: "", model: "model", apiKeyEnabled: false, hasApiKey: false, apiKey: "", engineDir: "", engineDirVerified: false };
function projectSession() {
  const session = new ProjectEditSession(() => {});
  session.replace(project);
  session.persistence = {
    save: async (value) => {
      await mocks.saveProject(value);
      return true;
    },
    wait: async () => true,
    pause: () => {},
    resume: () => {},
    rebasePending: () => {},
  };
  return session;
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  mocks.saveProject.mockReset().mockResolvedValue(project);
  mocks.startScriptAssistantJob.mockReset().mockResolvedValue({
    id: "job",
    operation: "paraphrase",
    status: "completed",
    phase: "completed",
    message: "完了",
    overallProgress: 100,
    groups: [],
  });
  mocks.scriptAssistantJob.mockReset();
  mocks.cancelScriptAssistantJob.mockReset();
  mocks.suggestScriptAssistant.mockReset().mockResolvedValue({ instruction: "前後の会話から自然に自己紹介へつなげる。" });
});

describe("LineAssistantDialog line insertion", () => {
  it("generates from surrounding context while the script content is blank", async () => {
    render(<LineAssistantDialog projectSession={projectSession()} project={project} connection={connection} connectionReady target={{ kind: "insert", sceneId: "scene", beforeLineId: "two" }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={vi.fn()} />);

    expect(screen.getByRole("textbox", { name: "テーマ／状況" })).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({ operation: "insert", instruction: "", scene_id: "scene", before_line_id: "two" });
  });

  it("keeps the insertion target switch between lines and minutes", async () => {
    render(<LineAssistantDialog projectSession={projectSession()} project={project} connection={connection} connectionReady target={{ kind: "insert", sceneId: "scene", beforeLineId: "two" }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={vi.fn()} />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "生成目標" }), "minutes");
    const minutes = screen.getByRole("spinbutton", { name: "分" });
    await userEvent.clear(minutes);
    await userEvent.type(minutes, "1.5");
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({ target_kind: "minutes", target_minutes: 1.5 });
  });

  it("suggests script content from context when the theme is blank", async () => {
    render(<LineAssistantDialog projectSession={projectSession()} project={project} connection={connection} connectionReady target={{ kind: "insert", sceneId: "scene", beforeLineId: "two" }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /おまかせ台本/ }));

    await waitFor(() => expect(mocks.suggestScriptAssistant).toHaveBeenCalledWith(expect.objectContaining({ instruction: "", scene_id: "scene", before_line_id: "two" })));
    expect(screen.getByRole("textbox", { name: "テーマ／状況" })).toHaveValue("前後の会話から自然に自己紹介へつなげる。");
  });

  it("starts with only cast addition when the script has no speakers", async () => {
    const emptyProject: StudioProject = { ...project, scenes: [{ ...project.scenes[0], lines: [] }] };
    render(<LineAssistantDialog projectSession={projectSession()} project={emptyProject} connection={connection} connectionReady target={{ kind: "insert", sceneId: "scene", beforeLineId: "" }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "対象キャスト" })).toHaveTextContent("1");
    expect(within(screen.getByRole("list", { name: "選択中の生成対象キャスト" })).queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "生成目標数" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "台本内容" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /提案を生成/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "生成対象キャストを追加" }));
    const menu = screen.getByRole("listbox", { name: "追加する生成対象キャスト" });
    expect(screen.getByRole("dialog", { name: "AIで台本を編集" })).not.toContainElement(menu);
    expect(menu).toHaveClass("is-portal");
    expect(within(menu).getAllByRole("option")[0]).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox", { name: "追加する生成対象キャスト" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成対象キャストを追加" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "生成対象キャストを追加" }));
    await userEvent.click(screen.getByRole("option", { name: "彩" }));
    expect(screen.getByRole("heading", { name: "キャスト設定" })).toHaveTextContent("2");
    expect(screen.getByRole("heading", { name: "生成目標数" })).toHaveTextContent("3");
    expect(screen.getByRole("heading", { name: "台本内容" })).toHaveTextContent("4");
    expect(screen.getByRole("heading", { name: "詳細設定" })).toHaveTextContent("5");
    expect(screen.getByRole("heading", { name: "台本生成" })).toHaveTextContent("6");
    expect(screen.getByRole("checkbox", { name: "彩：表情EMOJIを使う" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: /提案を生成/ })).toBeInTheDocument();
  });

  it("sends the enabled simultaneous speech option", async () => {
    render(
      <LineAssistantDialog
        projectSession={projectSession()}
        project={project}
        connection={{
          provider: "ollama",
          baseUrl: "",
          model: "model",
          apiKeyEnabled: false,
          hasApiKey: false,
          apiKey: "",
          engineDir: "",
          engineDirVerified: false,
        }}
        connectionReady
        target={{ kind: "insert", sceneId: "scene", beforeLineId: "two" }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "同時発話を使う" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "被せ・割り込みを使う" })).toBeChecked();
    await userEvent.type(screen.getByRole("textbox", { name: "テーマ／状況" }), "同時発話を活かして挨拶から始まる会話にする。");
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({
      operation: "insert",
      scene_id: "scene",
      before_line_id: "two",
      target_line_count: 2,
      simultaneous_cues: true,
      overlapping_speech: true,
      performance_gap_min: -2,
      character_ids: ["a", "b"],
    });
  });
});
