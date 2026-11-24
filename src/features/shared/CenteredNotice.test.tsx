// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CenteredNotice } from "./CenteredNotice";

it("renders one shared centered status card in a danger or neutral tone", () => {
  const { rerender } = render(
    <CenteredNotice tone="danger">
      <strong>削除しますか？</strong>
    </CenteredNotice>,
  );
  expect(screen.getByRole("status")).toHaveClass("centered-notice", "is-danger");
  expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  rerender(
    <CenteredNotice tone="neutral" label="通知" interactive>
      <p>追加しました。</p>
    </CenteredNotice>,
  );
  expect(screen.getByRole("status", { name: "通知" })).toHaveClass("centered-notice", "is-neutral", "is-interactive");
  expect(screen.getByRole("status", { name: "通知" })).not.toHaveClass("is-danger");
});
