import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DraftJob } from "../../types";
import { DraftCompletionDialog } from "./DraftCompletionDialog";

describe("draft completion accounting", () => {
  it("omits completion status prose and excludes unconfirmed usage from displayed totals", async () => {
    const job = {
      title: "自己紹介",
      startedAt: 0,
      completedAt: 252000,
      appendedLines: 57,
      estimatedSeconds: 458,
      llmCallCount: 12,
      transportCallCount: 36,
      partialReason: "dialogue_call_failures,incomplete_developments,duration_out_of_range",
      lengthAccepted: false,
      tokenUsageClassification: "partial",
      tokenUsage: { inputTokens: 19076, outputTokens: 3839, totalTokens: 25063, cachedInputTokens: 5240, unknownUsageCalls: 7, unconfirmedInputTokens: 78122, unattributedTokens: 2148, inputEstimated: false, outputEstimated: false, totalEstimated: false, cachedInputEstimated: false },
    } as DraftJob;
    render(<DraftCompletionDialog job={job} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "AI台本の生成結果" })).toBeInTheDocument();
    expect(screen.queryByText("書き終えていない展開があります。自動で追加生成はしていません。")).not.toBeInTheDocument();
    expect(screen.getByText("19,076")).toBeInTheDocument();
    expect(screen.getByText("25,063")).toBeInTheDocument();
    expect(screen.queryByText("97,198")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("使用量の補足"));
    expect(screen.getByText(/78,122 token。実消費量ではない/)).toBeVisible();
    expect(screen.getByText(/78,122 token。実消費量ではない/)).toBeInTheDocument();
    expect(screen.getByText(/使用量を取得できなかった生成が 7 回/)).toBeInTheDocument();
    expect(screen.getByText(/2,148 token/)).toBeInTheDocument();
    expect(screen.getByText("36 回")).toBeInTheDocument();
    expect(screen.queryByText(/dialogue_call_failures/)).not.toBeInTheDocument();
  });

  it.each(["openai", "scena-local", "ollama", "lmstudio"] as const)("keeps the same rows for %s with missing metrics", (provider) => {
    const job = { provider, model: "long-model-name/".repeat(20), startedAt: 0, appendedLines: 27, estimatedSeconds: 181, llmCallCount: 3 } as DraftJob;
    const { container } = render(<DraftCompletionDialog job={job} onClose={vi.fn()} />);
    expect([...container.querySelectorAll("dt")].map((element) => element.textContent)).toEqual([
      "発話行",
      "同時発話",
      "推定尺",
      "指定時間",
      "生成場面",
      "部分継続",
      "生成所要時間",
      "接続方式",
      "モデル",
      "生成処理（再試行を除く）",
      "HTTP通信（再試行を含む）",
      "入力token",
      "出力token",
      "合計token",
      "キャッシュ入力token",
      "数値の確かさ",
    ]);
    expect(screen.getByText("合計token").nextElementSibling).toHaveTextContent("未取得");
    expect(screen.getByText("キャッシュ入力token").nextElementSibling).toHaveTextContent("未取得");
    expect(container.querySelector(".draft-completion-grid")).toBeNull();
    expect(screen.getByRole("button", { name: "閉じる" })).toBeVisible();
  });

  it("never presents planned but missing scenes as generated", () => {
    const job = { startedAt: 0, appendedLines: 2, estimatedSeconds: 10, llmCallCount: 3, plannedDevelopments: 8, completedDevelopments: 1, completedChunks: 2, partialReason: "dialogue_budget_exhausted,incomplete_developments" } as DraftJob;
    render(<DraftCompletionDialog job={job} onClose={vi.fn()} />);
    expect(screen.getByText("生成場面").nextElementSibling).toHaveTextContent("1 場面");
    expect(screen.getByRole("heading", { name: "AI台本の生成結果" })).toBeVisible();
    expect(screen.queryByText(/生成回数の上限/)).not.toBeInTheDocument();
  });

  it("distinguishes reported zero cache usage from missing cache usage", () => {
    const job = { startedAt: 0, appendedLines: 0, estimatedSeconds: 0, llmCallCount: 3, tokenUsage: { inputTokens: 100, outputTokens: 20, totalTokens: 120, cachedInputTokens: 0, cachedInputEstimated: false }, tokenUsageClassification: "reported" } as DraftJob;
    const { rerender } = render(<DraftCompletionDialog job={job} onClose={vi.fn()} />);
    expect(screen.getByText("キャッシュ入力token").nextElementSibling).toHaveTextContent(/^0$/);
    rerender(<DraftCompletionDialog job={{ ...job, tokenUsage: { ...job.tokenUsage!, cachedInputEstimated: true } }} onClose={vi.fn()} />);
    expect(screen.getByText("キャッシュ入力token").nextElementSibling).toHaveTextContent("未取得");
  });
});
