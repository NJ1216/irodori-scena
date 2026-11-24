import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { CastExportDialog } from "./CastExportDialog";

const { chooseDirectory, defaultExportDirectory } = vi.hoisted(() => ({
  chooseDirectory: vi.fn(),
  defaultExportDirectory: vi.fn(async () => "C:\\Users\\tester\\Desktop"),
}));

vi.mock("../../api", () => ({
  api: { exportCasts: vi.fn() },
  chooseDirectory,
  defaultExportDirectory,
}));

const characters = [
  { id: "a", name: "彩", profile: "", voiceKeywords: "", avatarThumbnailUrl: "/a.png", referenceAudioUrl: "/a.wav", referenceFile: "/a.wav", createdAt: 1 },
  { id: "b", name: "蓮", profile: "", voiceKeywords: "", referenceAudioUrl: "/b.wav", referenceFile: "/b.wav", createdAt: 1 },
];

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    disconnect() {}
  },
);

it("starts with no cast selected and defaults its destination to the OS desktop", async () => {
  render(<CastExportDialog characters={characters} onClose={vi.fn()} />);
  expect(screen.getByRole("button", { name: "エクスポート" })).toBeDisabled();
  expect(await screen.findByLabelText("保存先")).toHaveValue("C:\\Users\\tester\\Desktop");
  expect(defaultExportDirectory).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "フォルダを選択" })).toBeVisible();
  const castButtons = screen.getByRole("group", { name: "エクスポートするキャスト" }).querySelectorAll("button");
  expect(castButtons).toHaveLength(2);
  expect(castButtons[0]).toHaveAttribute("aria-pressed", "false");
  const thumbnail = document.querySelector(".cast-export-picker .draft-cast-picker-avatar img");
  expect(thumbnail).toHaveAttribute("src", "/a.png");
  expect(thumbnail).toHaveAttribute("loading", "lazy");
  expect(castButtons[1].querySelector(".draft-cast-picker-avatar")).toHaveTextContent("蓮");
  await userEvent.click(screen.getByRole("button", { name: "すべて選択" }));
  expect(castButtons[0]).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("2 人選択")).toBeVisible();
  expect(screen.getByRole("button", { name: "エクスポート" })).toBeEnabled();
});
