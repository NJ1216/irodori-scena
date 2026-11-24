// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProjectLoadingOverlay } from "./ProjectLoadingOverlay";

describe("ProjectLoadingOverlay", () => {
  it("blocks with an explicit loading status until the project is ready", () => {
    const { rerender } = render(<ProjectLoadingOverlay visible />);

    expect(screen.getByRole("status", { name: "プロジェクトを読み込み中" })).toHaveTextContent("台本と音声の準備が完了するまでお待ちください。");

    rerender(<ProjectLoadingOverlay visible={false} />);
    expect(screen.queryByRole("status", { name: "プロジェクトを読み込み中" })).not.toBeInTheDocument();
  });
});
