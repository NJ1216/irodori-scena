import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LineStatusIcon } from "./LineStatusIcon";
import { QuickTooltip } from "../shared/QuickTooltip";

describe("LineStatusIcon", () => {
  afterEach(() => vi.useRealTimers());

  it("shows its tooltip quickly when the icon itself is hovered", () => {
    vi.useFakeTimers();
    const { container } = render(
      <>
        <LineStatusIcon name="gap" tooltip="発話間隔（空欄で共通設定）" />
        <QuickTooltip />
      </>,
    );
    const anchor = container.querySelector(".line-status-tooltip-anchor");
    expect(anchor).not.toBeNull();

    fireEvent.mouseEnter(anchor!);
    act(() => vi.advanceTimersByTime(79));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("tooltip")).toHaveTextContent("発話間隔（空欄で共通設定）");

    fireEvent.mouseLeave(anchor!);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
