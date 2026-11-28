import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TokenUsageMenu } from "./TokenUsageMenu";

describe("TokenUsageMenu", () => {
  it("shows session totals and operation-level history", () => {
    const onReset = vi.fn();
    const usage = {
      inputTokens: 1000,
      outputTokens: 234,
      totalTokens: 1234,
      cachedInputTokens: 50,
      inputEstimated: false,
      outputEstimated: true,
      totalEstimated: false,
      cachedInputEstimated: false,
    };
    render(
      <TokenUsageMenu
        onReset={onReset}
        usage={{
          sessionStartedAt: 1,
          classification: "partial",
          total: usage,
          history: [
            {
              id: "one",
              name: "AI台本生成",
              provider: "openai",
              model: "gpt-test",
              status: "completed",
              startedAt: 1,
              completedAt: 2,
              callCount: 2,
              classification: "partial",
              usage,
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "セッションtoken使用量" })).toHaveTextContent("token 1,234");
    expect(screen.getByLabelText("セッションtoken使用量メニュー")).toHaveTextContent("AI台本生成");
    expect(screen.getByLabelText("セッションtoken使用量メニュー")).toHaveTextContent("一部概算");
    expect(screen.getByRole("button", { name: "リセット" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "リセット" }));
    expect(onReset).toHaveBeenCalledOnce();
    expect(screen.getByText("うちキャッシュ").nextElementSibling).toHaveTextContent("50");
    expect(screen.getByLabelText("セッションtoken使用量メニュー")).toHaveTextContent("入力 1,000（キャッシュ 50）");
  });

  it("shows unreported cache reuse as unknown rather than zero", () => {
    const unreported = {
      inputTokens: 900,
      outputTokens: 100,
      totalTokens: 1000,
      cachedInputTokens: 0,
      inputEstimated: false,
      outputEstimated: false,
      totalEstimated: false,
      cachedInputEstimated: true,
    };
    const reportedZero = { ...unreported, cachedInputEstimated: false };
    const operation = {
      id: "local",
      name: "AI台本生成",
      provider: "ollama",
      model: "gemma",
      status: "completed" as const,
      startedAt: 1,
      completedAt: 2,
      callCount: 1,
      classification: "reported" as const,
      usage: unreported,
    };
    const { rerender } = render(<TokenUsageMenu onReset={vi.fn()} usage={{ sessionStartedAt: 1, classification: "reported", total: unreported, history: [operation] }} />);
    expect(screen.getByText("うちキャッシュ").nextElementSibling).toHaveTextContent("不明");
    expect(screen.getByLabelText("セッションtoken使用量メニュー")).toHaveTextContent("入力 900（キャッシュ 不明）");
    rerender(<TokenUsageMenu onReset={vi.fn()} usage={{ sessionStartedAt: 1, classification: "reported", total: reportedZero, history: [] }} />);
    expect(screen.getByText("うちキャッシュ").nextElementSibling).toHaveTextContent("0");
  });
});
