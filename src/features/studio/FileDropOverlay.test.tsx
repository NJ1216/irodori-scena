import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FileDropOverlay } from "./FileDropOverlay";

describe("FileDropOverlay", () => {
  it("identifies a project drop as a script project", () => {
    const { container } = render(<FileDropOverlay drop={{ kind: "project", path: "story.scena", unsupported: 0 }} />);
    expect(screen.getByText("SCENA 台本プロジェクト")).toBeVisible();
    expect(container.querySelector('[data-kind="project"] .file-drop-icon')).toBeTruthy();
  });

  it("identifies cast data and shows its count", () => {
    const { container } = render(<FileDropOverlay drop={{ kind: "casts", paths: ["a.scenacast", "b.scenacast"], unsupported: 0 }} />);
    expect(screen.getByText("SCENA キャストデータ")).toBeVisible();
    expect(screen.getByText("2件のキャストを読み込む")).toBeVisible();
    expect(container.querySelector('[data-kind="casts"] .file-drop-icon')).toBeTruthy();
  });
});
