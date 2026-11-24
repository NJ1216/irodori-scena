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
  });
});
