import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DraftJob, LlmConnection, StudioProject } from "../../types";
import type { DraftComposerState } from "../studio/types";
import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import { DraftView } from "./DraftView";
import { displayedDraftProgress } from "./draftProgress";
import { api } from "../../api";

class ResizeObserverMock {
  observe() {}
  disconnect() {}
}

vi.stubGlobal("ResizeObserver", ResizeObserverMock);

const project = {
  settings: { speechRate: 1.2, lineGap: 0.7 },
  characters: [],
} as unknown as StudioProject;

const projectWithCast = {
  ...project,
  characters: [{ id: "cast-a", name: "あかり" }],
} as unknown as StudioProject;

const projectWithTwoCasts = {
  ...project,
  characters: [
    { id: "cast-a", name: "あかり" },
    { id: "cast-b", name: "ひかり" },
  ],
} as unknown as StudioProject;

const connection = {
  provider: "ollama",
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "test-model",
  apiKeyEnabled: false,
  hasApiKey: false,
  apiKey: "",
} as LlmConnection;

const composer: DraftComposerState = {
  simultaneousCues: true,
  overlappingSpeech: true,
  selectedIds: [],
  minutes: 3,
  theme: "テスト用のテーマです。",
  apiKey: "dummy",
  provider: "ollama",
  baseUrl: connection.baseUrl,
  model: connection.model,
  castSettings: {},
  performance: {
    speechRateMin: 0.85,
    speechRateMax: 1.35,
    gapMin: 0,
    gapMax: 5,
    allowedEmojis: IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji),
  },
};

function ControlledDraftView({ withCast = false, selected = false, emptyTheme = false }: { withCast?: boolean; selected?: boolean; emptyTheme?: boolean }) {
  const [state, setState] = useState({ ...composer, selectedIds: selected ? ["cast-a"] : [], theme: emptyTheme ? "" : composer.theme });
  return <DraftView project={withCast ? projectWithCast : project} connection={connection} job={null} busy={null} composer={state} onComposerChange={setState} onStartJob={vi.fn()} onCancelJob={vi.fn(async () => {})} onNotice={vi.fn()} onBusy={vi.fn()} />;
}

function ConnectionSyncDraftView({ nextConnection }: { nextConnection: LlmConnection }) {
  const [state, setState] = useState({ ...composer, selectedIds: ["cast-a"] });
  return <DraftView project={projectWithCast} connection={nextConnection} job={null} busy={null} composer={state} onComposerChange={setState} onStartJob={vi.fn()} onCancelJob={vi.fn(async () => {})} onNotice={vi.fn()} onBusy={vi.fn()} />;
}

function TwoCastDraftView() {
  const [state, setState] = useState({ ...composer, selectedIds: ["cast-a", "cast-b"] });
  return <DraftView project={projectWithTwoCasts} connection={connection} job={null} busy={null} composer={state} onComposerChange={setState} onStartJob={vi.fn()} onCancelJob={vi.fn(async () => {})} onNotice={vi.fn()} onBusy={vi.fn()} />;
}

describe("draft progress", () => {
  it("previews dialogue percentage from streamed characters and returns to confirmed progress", () => {
    const dialogue = { phase: "dialogue", overallProgress: 20, receivedCharacters: 200, estimatedGeneratedCharacters: 500 } as DraftJob;
    expect(displayedDraftProgress(dialogue, 0, 1_000, 0)).toBe(54.5);
    expect(displayedDraftProgress({ ...dialogue, estimatedGeneratedCharacters: 2_000 }, 0, 1_000, 0)).toBe(89);
    expect(displayedDraftProgress({ ...dialogue, receivedCharacters: 0, estimatedGeneratedCharacters: null, overallProgress: 27 }, 100, 1_000, 0)).toBe(27);
  });
});

describe("DraftView", () => {
  it("advances context and planning by one percent every thirty seconds within their ranges", () => {
    const context = { phase: "context", overallProgress: 0 } as DraftJob;
    expect(displayedDraftProgress(context, 0, 1_000, 0)).toBe(0);
    expect(displayedDraftProgress(context, 0, 1_000, 30)).toBe(1);
    expect(displayedDraftProgress(context, 0, 1_000, 270)).toBe(9);
    expect(displayedDraftProgress(context, 0, 1_000, 600)).toBe(9);
    const planning = { phase: "planning", overallProgress: 10 } as DraftJob;
    expect(displayedDraftProgress(planning, 0, 1_000, 0)).toBe(10);
    expect(displayedDraftProgress(planning, 0, 1_000, 30)).toBe(11);
    expect(displayedDraftProgress(planning, 0, 1_000, 270)).toBe(19);
    expect(displayedDraftProgress(planning, 0, 1_000, 600)).toBe(19);
  });

  it("keeps the AI draft page mounted when the duration changes", () => {
    render(<ControlledDraftView withCast selected />);

    fireEvent.change(screen.getByRole("slider", { name: "だいたいの総尺（分）" }), {
      target: { value: "4" },
    });

    expect(screen.getByRole("heading", { name: "AIに台本の下書きを頼む" })).toBeInTheDocument();
    expect(screen.getByText("4分")).toBeInTheDocument();
  });

  it("sends the current duration when suggesting a theme", async () => {
    const user = userEvent.setup();
    const suggestion = vi.spyOn(api, "suggestTheme").mockResolvedValue({ theme: "提案されたテーマ" });
    render(<ControlledDraftView withCast selected />);

    fireEvent.change(screen.getByRole("slider", { name: "だいたいの総尺（分）" }), {
      target: { value: "10" },
    });
    await user.click(screen.getByRole("button", { name: /アイディアを広げる/ }));

    await waitFor(() => expect(suggestion).toHaveBeenCalledWith(expect.objectContaining({ theme: "テスト用のテーマです。", target_minutes: 10 })));
    suggestion.mockRestore();
  });

  it("requests a random theme independently of the current theme text", async () => {
    const user = userEvent.setup();
    const suggestion = vi.spyOn(api, "suggestTheme").mockResolvedValue({ theme: "ランダムなテーマ" });
    render(<ControlledDraftView withCast selected />);

    await user.click(screen.getByRole("button", { name: /おまかせ台本/ }));

    await waitFor(() => expect(suggestion).toHaveBeenCalledWith(expect.objectContaining({ theme: "", target_minutes: 3 })));
    expect(screen.getByRole("textbox", { name: "テーマ／状況" })).toHaveValue("ランダムなテーマ");
    suggestion.mockRestore();
  });

  it("reveals details and generation only after the script content has text", async () => {
    const user = userEvent.setup();
    render(<ControlledDraftView withCast selected emptyTheme />);

    expect(screen.getByRole("heading", { name: /台本内容/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /詳細設定/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /台本案を生成する/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /アイディアを広げる/ })).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: "テーマ／状況" }), "新しい台本案");
    expect(screen.getByRole("heading", { name: /詳細設定/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /台本生成/ })).toHaveTextContent("6");
    expect(screen.getByRole("button", { name: /台本案を生成する/ })).toBeInTheDocument();
  });

  it("updates the ready model when the saved connection changes", async () => {
    const { rerender } = render(<ConnectionSyncDraftView nextConnection={connection} />);
    const updatedConnection = { ...connection, model: "new-model" };

    rerender(<ConnectionSyncDraftView nextConnection={updatedConnection} />);

    await waitFor(() => expect(screen.getByText("Ollama（ローカル） · new-model")).toBeInTheDocument());
  });

  it("reveals later stages only after selecting a participating cast member", async () => {
    const user = userEvent.setup();
    render(<ControlledDraftView withCast />);

    expect(screen.getByRole("heading", { name: /参加キャスト/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /キャスト設定/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /生成目標数/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /詳細設定/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /あかり/ }));
    expect(screen.getByRole("heading", { name: /キャスト設定/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /生成目標数/ })).toHaveTextContent("3");
    expect(screen.getByRole("heading", { name: /台本内容/ })).toHaveTextContent("4");
    expect(screen.getByRole("heading", { name: /詳細設定/ })).toHaveTextContent("5");
    expect(screen.getByLabelText("話速の最小値")).toBeInTheDocument();
    expect(screen.getByText("表情付けに利用する絵文字（45/45）")).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByLabelText("👂：囁き・耳元の音"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("囁き・耳元の音");
    await user.click(screen.getByRole("button", { name: "全解除" }));
    expect(screen.getByText("表情付けに利用する絵文字（0/45）")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /あかり/ }));
    expect(screen.queryByRole("heading", { name: /キャスト設定/ })).not.toBeInTheDocument();
  });

  it("keeps simultaneous cues and overlaps independent and hides them below two casts", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<TwoCastDraftView />);

    const checkbox = screen.getByRole("checkbox", { name: /同時発話を使う/ });
    const overlap = screen.getByRole("checkbox", { name: /被せ・割り込みを使う/ });
    expect(checkbox).toBeEnabled();
    expect(checkbox).toBeChecked();
    expect(overlap).toBeChecked();

    await user.click(checkbox);
    expect(screen.getByRole("heading", { name: "AIに台本の下書きを頼む" })).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
    expect(overlap).toBeChecked();

    await user.click(overlap);
    expect(overlap).not.toBeChecked();

    await user.click(checkbox);
    expect(screen.getByRole("heading", { name: "AIに台本の下書きを頼む" })).toBeInTheDocument();
    expect(checkbox).toBeChecked();

    rerender(<ControlledDraftView withCast selected />);
    expect(screen.queryByRole("checkbox", { name: /同時発話を使う/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /被せ・割り込みを使う/ })).not.toBeInTheDocument();
  });

  it("sends the separate cue and overlap settings when generating", async () => {
    const user = userEvent.setup();
    const start = vi.spyOn(api, "startAiJob").mockResolvedValue({} as DraftJob);
    render(<TwoCastDraftView />);

    await user.click(screen.getByRole("checkbox", { name: /同時発話を使う/ }));
    await user.click(screen.getByRole("button", { name: /台本案を生成する/ }));

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({ simultaneous_cues: false, overlapping_speech: true })));
    start.mockRestore();
  });

  it("disables both multi-cast effects in a single-cast generation request", async () => {
    const user = userEvent.setup();
    const start = vi.spyOn(api, "startAiJob").mockResolvedValue({} as DraftJob);
    render(<ControlledDraftView withCast selected />);

    await user.click(screen.getByRole("button", { name: /台本案を生成する/ }));

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({ simultaneous_cues: false, overlapping_speech: false })));
    start.mockRestore();
  });
});
