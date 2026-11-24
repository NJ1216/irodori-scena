import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DraftJob } from "../../types";
import { DraftGenerationDialog, DraftResult } from "./DraftStatus";

const job = (patch: Partial<DraftJob> = {}): DraftJob =>
  ({
    id: "draft-1",
    status: "generating",
    phase: "dialogue",
    message: "台詞を執筆しています",
    title: "雨の駅",
    totalChunks: 2,
    currentChunk: 1,
    completedChunks: 1,
    appendedLines: 4,
    estimatedSeconds: 61,
    llmCallCount: 2,
    dialogueAttempt: 1,
    currentChunkAcceptedCharacters: 100,
    currentChunkTargetCharacters: 200,
    requestedCharacters: 200,
    receivedCharacters: 50,
    estimatedGeneratedCharacters: 175,
    receivedRecords: 2,
    acceptedCharactersTotal: 100,
    targetCharacters: 400,
    generatedCharacters: 150,
    overallProgress: 25,
    adaptiveYieldRatio: 1,
    yieldSamples: 1,
    performanceAttempt: 0,
    notationCompletedSteps: 0,
    notationTotalSteps: 3,
    performanceCompletedLines: 0,
    performanceTotalLines: 0,
    transitionCompleted: 0,
    transitionTotal: 0,
    performanceTextCorrections: 0,
    usedTokens: 12345,
    tokenUsageAvailable: true,
    startedAt: 1,
    chunks: [],
    ...patch,
  }) as DraftJob;

describe("draft status presentation", () => {
  it("keeps the ordinary integrated draft at three steps through internal finishing", () => {
    const { rerender } = render(<DraftGenerationDialog job={job()} elapsed={0} generatedCharacters={150} targetCharacters={400} overallProgress={40} onCancel={vi.fn(async () => {})} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("キャラクターの設定をまとめています")).toBeInTheDocument();
    expect(screen.getByText("台本のあらすじを作成中")).toBeInTheDocument();
    expect(screen.getByText("台詞を執筆中").closest("li")).toHaveClass("is-current");

    rerender(<DraftGenerationDialog job={job({ phase: "notation" })} elapsed={0} generatedCharacters={400} targetCharacters={400} overallProgress={93} onCancel={vi.fn(async () => {})} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("台詞を執筆中").closest("li")).toHaveClass("is-current");
  });

  it.each([
    ["notation", { draftFinishingStepRequired: true }, ["台本を仕上げています"]],
    ["performance", { performanceFallbackStepRequired: true }, ["演技と間を整えています"]],
    ["notation", { draftFinishingStepRequired: true, performanceFallbackStepRequired: true }, ["台本を仕上げています", "演技と間を整えています"]],
  ] as const)("adds and retains only required optional steps %#", (phase, flags, labels) => {
    render(<DraftGenerationDialog job={job({ phase, ...flags })} elapsed={0} generatedCharacters={400} targetCharacters={400} overallProgress={97} onCancel={vi.fn(async () => {})} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3 + labels.length);
    labels.forEach((label, index) => {
      const item = screen.getByText(label).closest("li");
      expect(item).toBeInTheDocument();
      expect(item).toHaveTextContent(String(4 + index));
    });
  });

  it("keeps a custom AI direction dialog to its explicit single step", () => {
    render(<DraftGenerationDialog job={job({ phase: "performance", draftFinishingStepRequired: true, performanceFallbackStepRequired: true })} elapsed={0} generatedCharacters={1} targetCharacters={2} overallProgress={50} onCancel={vi.fn(async () => {})} phases={[["direction", "選択した発話行を演出しています"]]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("選択した発話行を演出しています")).toBeInTheDocument();
  });

  it("shows deterministic progress and requests cancellation", async () => {
    const onCancel = vi.fn(async () => {});
    render(<DraftGenerationDialog job={job()} elapsed={65} generatedCharacters={150} targetCharacters={400} overallProgress={25} onCancel={onCancel} />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("経過時間")).toBeInTheDocument();
    expect(screen.getByText("1:05")).toBeInTheDocument();
    expect(screen.getByText("目標文字数")).toBeInTheDocument();
    expect(screen.getByText("175 / 400文字")).toBeInTheDocument();
    expect(screen.getByText("全体進捗")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("台詞を執筆しています")).toBeInTheDocument();
    expect(screen.queryByText(/使用 token 数/)).not.toBeInTheDocument();
    expect(screen.queryByText(/コンテキスト|token|最大 .*文字|M4Max|128 GB/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "生成をキャンセル" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("updates the in-flight character estimate and returns to confirmed characters", () => {
    const { rerender } = render(<DraftGenerationDialog job={job({ estimatedGeneratedCharacters: 175 })} elapsed={1} generatedCharacters={150} targetCharacters={400} overallProgress={50} onCancel={vi.fn(async () => {})} />);
    expect(screen.getByText("175 / 400文字")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    rerender(<DraftGenerationDialog job={job({ estimatedGeneratedCharacters: 205 })} elapsed={2} generatedCharacters={150} targetCharacters={400} overallProgress={55} onCancel={vi.fn(async () => {})} />);
    expect(screen.getByText("205 / 400文字")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
    rerender(<DraftGenerationDialog job={job({ estimatedGeneratedCharacters: null, receivedCharacters: 0, generatedCharacters: 180 })} elapsed={3} generatedCharacters={180} targetCharacters={400} overallProgress={30} onCancel={vi.fn(async () => {})} />);
    expect(screen.getByText("180 / 400文字")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "30");
  });

  it("switches later phases from the frozen character count to measured work", () => {
    const { rerender } = render(<DraftGenerationDialog job={job({ phase: "notation", message: "確認結果を受信しています", notationCompletedSteps: 2 })} elapsed={2} generatedCharacters={400} targetCharacters={400} overallProgress={56} onCancel={vi.fn(async () => {})} />);
    expect(screen.getByText("確認結果を受信しています")).toBeInTheDocument();
    expect(screen.getByText("仕上げ")).toBeInTheDocument();
    expect(screen.getByText("2 / 3工程")).toBeInTheDocument();
    expect(screen.queryByText(/目標文字数/)).not.toBeInTheDocument();
    rerender(
      <DraftGenerationDialog
        job={job({
          phase: "performance",
          message: "LLMの応答を待っています",
          performanceCompletedLines: 3,
          performanceTotalLines: 8,
        })}
        elapsed={3}
        generatedCharacters={400}
        targetCharacters={400}
        overallProgress={75}
        onCancel={vi.fn(async () => {})}
      />,
    );
    expect(screen.getByText("演技設定")).toBeInTheDocument();
    expect(screen.getByText("3 / 8行")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "75");
  });
});

describe("draft result presentation", () => {
  it("keeps the completed summary wording stable", () => {
    render(<DraftResult job={job({ status: "completed" })} />);
    expect(screen.getByText("ADDED TO SCRIPT")).toBeInTheDocument();
    expect(screen.getByText(/4 行を追加/)).toBeInTheDocument();
    expect(screen.queryByText(/チャンク/)).not.toBeInTheDocument();
    expect(screen.getByText(/1分1秒/)).toBeInTheDocument();
  });

  it("does not surface a completed draft shortfall as an error", () => {
    render(
      <DraftResult
        job={job({
          status: "completed",
          targetReached: false,
          shortfallCharacters: 97,
          actualCharacters: 11_903,
          minimumAcceptableCharacters: 11_500,
          targetCharacters: 12_000,
        })}
      />,
    );
    expect(screen.getByText("ADDED TO SCRIPT")).toBeInTheDocument();
    expect(screen.getByText(/生成済みの台本は自動的に追加されました/)).toBeInTheDocument();
    expect(screen.queryByText(/不足/)).not.toBeInTheDocument();
  });

  it("does not surface a valid below-minimum draft as an error", () => {
    render(
      <DraftResult
        job={job({
          status: "completed",
          targetReached: false,
          lengthAccepted: false,
          actualCharacters: 9_569,
          minimumAcceptableCharacters: 10_300,
          targetCharacters: 10_800,
        })}
      />,
    );
    expect(screen.getByText("ADDED TO SCRIPT")).toBeInTheDocument();
    expect(screen.getByText(/生成済みの台本は自動的に追加されました/)).toBeInTheDocument();
    expect(screen.queryByText(/不足/)).not.toBeInTheDocument();
    expect(screen.queryByText(/台本は追加していません/)).not.toBeInTheDocument();
  });

  it("does not expose partial-generation diagnostics in a completed result", () => {
    render(
      <DraftResult
        job={job({
          status: "completed",
          targetReached: true,
          partialReason: "dialogue_call_failures",
        })}
      />,
    );
    expect(screen.getByText("ADDED TO SCRIPT")).toBeInTheDocument();
    expect(screen.getByText(/生成済みの台本は自動的に追加されました/)).toBeInTheDocument();
    expect(screen.queryByText(/不足/)).not.toBeInTheDocument();
  });
});
