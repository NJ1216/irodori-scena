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
function renderAssistant(value: StudioProject, lineIds: string[]) {
  render(<LineAssistantDialog projectSession={projectSession()} project={value} connection={connection} connectionReady target={{ kind: "rewrite", lineIds }} busy={null} onBusy={vi.fn()} onClose={vi.fn()} onGenerated={vi.fn()} onNotice={vi.fn()} />);
}

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

describe("LineAssistantDialog", () => {
  it("hides generation targets for paraphrasing while preserving its internal line mapping", async () => {
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
        target={{ kind: "rewrite", lineIds: ["one", "two"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: "同じ内容の言い換え" })).toBeChecked();
    expect(screen.getByRole("heading", { name: "対象の行" })).toBeInTheDocument();
    expect(screen.getByLabelText("書き直し対象 2行: 1〜2")).toHaveTextContent("1〜2");
    for (const [heading, number] of [
      ["対象の行", 1],
      ["書き直し方式", 2],
      ["対象キャスト", 3],
      ["内容と演出", 4],
    ] as const)
      expect(screen.getByRole("heading", { name: heading }).textContent).toContain(String(number));
    expect(screen.queryByText("前の台本全体と後続3行を参照し、適用前に提案を確認できます。")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "生成目標" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "行数" })).not.toBeInTheDocument();
    expect(screen.getByText("内容と行数を保ち、表現とリズムを変えます")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("空欄でも内容と行数を保ち、別の表現に言い換えます。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({
      operation: "paraphrase",
      line_ids: ["one", "two"],
      character_ids: ["a", "b"],
      target_kind: "lines",
      target_line_count: 2,
      instruction: "",
      simultaneous_cues: false,
    });
  });

  it("reveals the generation target inside rewrite mode for a complete rewrite", async () => {
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
        target={{ kind: "rewrite", lineIds: ["one", "two"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("radio", { name: "完全に書き直す" }));

    expect(screen.getByText("前後のつながりだけ守り、会話の運びから組み直します")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("空欄でも前後のつながりを守り、会話の運びから組み直します。")).toBeInTheDocument();

    const generationSection = screen.getByRole("heading", { name: "生成目標数" }).closest("section");
    expect(generationSection).not.toBeNull();
    expect(screen.getByRole("heading", { name: "生成目標数" })).toHaveTextContent("4");
    expect(screen.getByRole("heading", { name: "内容と演出" })).toHaveTextContent("5");
    expect(within(generationSection!).getByRole("combobox", { name: "生成目標" })).toHaveValue("lines");
    const lineCount = within(generationSection!).getByRole("spinbutton", { name: "行数" });
    expect(lineCount).toHaveValue(2);
    await userEvent.clear(lineCount);
    expect(lineCount).toHaveValue(null);
    await userEvent.type(lineCount, "8");
    expect(lineCount).toHaveValue(8);
    expect(lineCount.parentElement).toHaveTextContent("行");
    await userEvent.selectOptions(within(generationSection!).getByRole("combobox", { name: "生成目標" }), "minutes");
    const minutes = within(generationSection!).getByRole("spinbutton", { name: "分" });
    expect(minutes.parentElement).toHaveTextContent("分");
    expect(screen.getByRole("heading", { name: "内容と演出" })).toBeInTheDocument();
  });
});

describe("LineAssistantDialog cast and target settings", () => {
  it("keeps a sparse selection until a range is applied, then restores it", async () => {
    const value: StudioProject = {
      ...project,
      scenes: [
        { ...project.scenes[0], lines: [...project.scenes[0].lines, { id: "three", characterId: "a", text: "三行目", stageDirection: "", takes: [], selectedTakeId: null }] },
        { id: "scene-two", title: "公園", lines: [{ id: "four", characterId: "b", text: "四行目", stageDirection: "", takes: [], selectedTakeId: null }] },
      ],
    };
    renderAssistant(value, ["one", "three"]);
    expect(screen.getByLabelText("書き直し対象 2行: 1、3")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "彩：メインキャスト" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "編集" }));
    expect(within(screen.getByRole("combobox", { name: "終了行" })).getByRole("option", { name: "公園 · 4行 · 四行目" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "終了行" }), "four");
    await userEvent.click(screen.getByRole("button", { name: "キャンセル" }));
    expect(screen.getByLabelText("書き直し対象 2行: 1、3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "編集" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "終了行" }), "four");
    await userEvent.click(screen.getByRole("button", { name: "適用" }));
    expect(screen.getByLabelText("書き直し対象 4行: 1〜4")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "完全に書き直す" }));
    expect(screen.getByRole("checkbox", { name: "彩：メインキャスト" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "元の選択に戻す" }));
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));
    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0].line_ids).toEqual(["one", "three"]);
  });

  it("sends per-cast settings with a cross-scene range", async () => {
    const value: StudioProject = { ...project, scenes: [...project.scenes, { id: "scene-two", title: "公園", lines: [{ id: "three", characterId: "a", text: "三行目", stageDirection: "", takes: [], selectedTakeId: null }] }] };
    renderAssistant(value, ["one"]);
    await userEvent.click(screen.getByRole("button", { name: "編集" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "終了行" }), "three");
    await userEvent.click(screen.getByRole("button", { name: "適用" }));
    await userEvent.click(screen.getByRole("radio", { name: "完全に書き直す" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "彩：表情EMOJIを使う" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "蓮：フィラーを多めに入れる" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "彩：メインキャスト" }));
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));
    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({
      line_ids: ["one", "two", "three"],
      cast_settings: {
        a: { emoji_expressions: true, filler_richness: false, appearance_priority: "main" },
        b: { emoji_expressions: false, filler_richness: true, appearance_priority: "standard" },
      },
    });
  });
  it("composes only the selected casts without content or emoji controls", async () => {
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
        target={{ kind: "rewrite", lineIds: ["one", "two"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("radio", { name: "キャスト構成" }));
    expect(screen.getByRole("radio", { name: "キャスト構成" })).toBeChecked();
    expect(screen.getByText("話者と行数を保ち、キャスト設定から外れたセリフを整えます")).toBeVisible();
    expect(screen.getByText("選択行に登場するキャストから、プロフィールとの整合を確認する対象を選びます")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "内容と演出" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "どのように／どんなテーマで" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "表情EMOJIを使う" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "同時発話の提案を許可" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "生成目標" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "蓮を生成対象から外す" }));
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));
    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({
      operation: "cast-compose",
      line_ids: ["one"],
      character_ids: ["a"],
      target_kind: "lines",
      target_line_count: 1,
      instruction: "",
      emoji_expressions: false,
      simultaneous_cues: false,
    });
  });
});

describe("LineAssistantDialog simultaneous cues and progress", () => {
  it("reserves enough rows for a lead-in and required simultaneous greeting", async () => {
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
        target={{ kind: "rewrite", lineIds: ["one"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("radio", { name: "完全に書き直す" }));
    await userEvent.type(screen.getByRole("textbox", { name: "どのように／どんなテーマで" }), "片方の掛け声で、動時発話の挨拶から始まる感じで。");
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    await waitFor(() => expect(mocks.startScriptAssistantJob).toHaveBeenCalledOnce());
    expect(mocks.startScriptAssistantJob.mock.calls[0][0]).toMatchObject({
      operation: "rewrite",
      target_line_count: 3,
      simultaneous_cues: true,
      character_ids: ["a", "b"],
    });
  });

  it("uses the shared AI draft progress dialog while generating", async () => {
    mocks.startScriptAssistantJob.mockResolvedValueOnce({
      id: "job",
      operation: "paraphrase",
      status: "generating",
      phase: "dialogue",
      message: "1/1 シーンの提案を生成しています…",
      overallProgress: 17,
    });
    mocks.scriptAssistantJob.mockReturnValue(new Promise(() => undefined));
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
        target={{ kind: "rewrite", lineIds: ["one", "two"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    expect(await screen.findByRole("heading", { name: "選択行を書き直しています" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "AI台本編集の全体進捗" })).toHaveAttribute("aria-valuenow", "17");
    expect(screen.getByText("台本の文脈を整理しています")).toBeInTheDocument();
    expect(screen.getByText("提案を生成しています")).toBeInTheDocument();
    expect(screen.getByText("全体進捗 17%")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "生成をキャンセル" })).toHaveLength(1);
  });

  it("shows the rewrite-plan phase only for complete rewrites", async () => {
    mocks.startScriptAssistantJob.mockResolvedValueOnce({
      id: "job",
      operation: "rewrite",
      status: "planning",
      phase: "rewrite-plan",
      message: "書き直し方針を組み立てています…",
      overallProgress: 20,
    });
    mocks.scriptAssistantJob.mockReturnValue(new Promise(() => undefined));
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
        target={{ kind: "rewrite", lineIds: ["one", "two"] }}
        busy={null}
        onBusy={vi.fn()}
        onClose={vi.fn()}
        onGenerated={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("radio", { name: "完全に書き直す" }));
    await userEvent.click(screen.getByRole("button", { name: /提案を生成/ }));

    expect(await screen.findByText("書き直し方針を組み立てています")).toBeInTheDocument();
    expect(screen.getByText("台本の文脈を整理しています")).toBeInTheDocument();
    expect(screen.getByText("提案を生成しています")).toBeInTheDocument();
  });
});
