// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { api } from "../../api";
import { ExportDialog } from "./ExportDialog";

vi.mock("../../api-runtime", () => ({ chooseDirectory: vi.fn().mockResolvedValue("/tmp/export"), defaultExportDirectory: vi.fn().mockResolvedValue("/Users/test/Desktop") }));
vi.mock("../../api", () => ({
  api: { rhubarbStatus: vi.fn().mockResolvedValue({ ready: true }) },
}));

const project = {
  version: 1,
  revision: 0,
  id: "project",
  title: "台本",
  candidates: [],
  characters: [],
  scenes: [
    {
      id: "scene",
      title: "場面",
      lines: [{ id: "line", characterId: "cast", text: "こんにちは", stageDirection: "", takes: [], selectedTakeId: null }],
    },
  ],
  settings: {
    speechRate: 1,
    steps: 16,
    textCfg: 1.5,
    voiceCfg: 2,
    seed: 1,
    quality: "fast",
    llmBaseUrl: "",
    llmModel: "",
  },
} satisfies StudioProject;

let stored: Record<string, string>;
beforeEach(() => {
  stored = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => stored[key] ?? null,
    setItem: (key: string, value: string) => {
      stored[key] = value;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("defaults the export destination to the operating system desktop", async () => {
  render(<ExportDialog project={project} job={null} onClose={vi.fn()} onStart={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "エクスポート" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "エクスポート" })).toBeInTheDocument();
  expect(await screen.findByDisplayValue("/Users/test/Desktop")).toBeInTheDocument();
});

it("restores LAB as split output with its required WAV", async () => {
  localStorage.setItem(
    "scena.export.settings.v1",
    JSON.stringify({
      layout: "joined",
      formats: ["wav", "subtitle_txt", "script_txt", "lab"],
      naming: ["sequence", "cast", "text"],
      scriptDelimiter: " ",
      quoteDialogue: true,
    }),
  );
  const onStart = vi.fn().mockResolvedValue(undefined);
  render(<ExportDialog project={project} job={null} onClose={vi.fn()} onStart={onStart} onCancel={vi.fn()} />);

  expect(screen.getByLabelText("口パクLAB")).toBeChecked();
  expect(screen.getByLabelText("WAV")).toBeChecked();
  expect(screen.getByLabelText("1ファイルに連結")).toBeEnabled();
  expect(screen.getByLabelText("字幕SRT")).toBeEnabled();
  expect(screen.getByLabelText("字幕SRT")).not.toBeChecked();
  await userEvent.click(screen.getByLabelText("字幕SRT"));
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await userEvent.click(screen.getByRole("button", { name: "エクスポート" }));

  await waitFor(() => expect(onStart).toHaveBeenCalledOnce());
  expect(onStart.mock.calls[0][0]).toMatchObject({
    destinationDir: "/tmp/export",
    layout: "split",
    formats: ["wav", "subtitle_txt", "script_txt", "lab", "srt"],
    scriptDelimiter: " ",
    quoteDialogue: true,
  });
});

it("hides LAB for joined export and removes it when switching from split", async () => {
  render(<ExportDialog project={project} job={null} onClose={vi.fn()} onStart={vi.fn()} onCancel={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("口パクLAB"));
  expect(screen.getByLabelText("口パクLAB")).toBeChecked();

  await userEvent.click(screen.getByLabelText("1ファイルに連結"));

  expect(screen.getByLabelText("1ファイルに連結")).toBeChecked();
  expect(screen.queryByLabelText("口パクLAB")).not.toBeInTheDocument();
  expect(screen.getByLabelText("WAV")).toBeChecked();

  await userEvent.click(screen.getByLabelText("発話行ごとに分割"));
  expect(screen.getByLabelText("口パクLAB")).not.toBeChecked();
});

it("asks before adding Rhubarb for the first LAB export", async () => {
  vi.mocked(api.rhubarbStatus).mockResolvedValueOnce({
    provider: "Rhubarb",
    version: "1.14.0",
    releaseId: "1.14.0-scena.1",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: false,
    ready: false,
    archiveBytes: 70_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
  });
  const onStart = vi.fn().mockResolvedValue(undefined);
  render(<ExportDialog project={project} job={null} onClose={vi.fn()} onStart={onStart} onCancel={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("口パクLAB"));
  expect(screen.getByLabelText("WAV")).toBeChecked();
  expect(screen.getByLabelText("1ファイルに連結")).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await userEvent.click(screen.getByRole("button", { name: "エクスポート" }));
  expect(await screen.findByRole("dialog", { name: "口パクLABにRhubarbを追加" })).toBeInTheDocument();
  expect(onStart).not.toHaveBeenCalled();
});

it("prompts for an addon hash update before a LAB export", async () => {
  vi.mocked(api.rhubarbStatus).mockResolvedValueOnce({
    provider: "Rhubarb",
    version: "1.14.0",
    releaseId: "new",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: true,
    ready: true,
    updateAvailable: true,
    archiveBytes: 200_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
  });
  const onStart = vi.fn();
  render(<ExportDialog project={project} job={null} onClose={vi.fn()} onStart={onStart} onCancel={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("口パクLAB"));
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await userEvent.click(screen.getByRole("button", { name: "エクスポート" }));
  expect(await screen.findByRole("dialog", { name: "口パクLAB用アドオンを更新" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "更新してエクスポート" })).toBeEnabled();
  expect(onStart).not.toHaveBeenCalled();
});

it("cancels a running LAB export from the dialog and prevents duplicate requests", async () => {
  const onClose = vi.fn();
  const onCancel = vi.fn();
  const runningJob = {
    id: "export-job",
    status: "aligning",
    message: "口形LABを解析しています… 12 / 34 行",
    currentLine: 34,
    completedLines: 34,
    generatedLines: 34,
    totalLines: 34,
    alignmentCompletedLines: 12,
    alignmentTotalLines: 34,
    startedAt: 0,
  } as const;
  const { rerender } = render(<ExportDialog project={project} job={runningJob} onClose={onClose} onStart={vi.fn()} onCancel={onCancel} />);

  expect(screen.getByRole("heading", { name: "エクスポート中" })).toBeInTheDocument();
  const cancel = screen.getByRole("button", { name: "キャンセル" });
  expect(cancel).toBeEnabled();
  await userEvent.click(cancel);
  expect(onCancel).toHaveBeenCalledOnce();
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByText("口形LABを解析しています… 12 / 34 行")).toBeInTheDocument();
  expect(screen.queryByText("LAB 12 / 34 行")).not.toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "12");
  expect(screen.getByRole("progressbar")).toHaveAttribute("max", "34");

  rerender(<ExportDialog project={project} job={{ ...runningJob, cancelRequested: true }} onClose={onClose} onStart={vi.fn()} onCancel={onCancel} />);
  expect(screen.getByRole("button", { name: "キャンセル中…" })).toBeDisabled();

  rerender(<ExportDialog project={project} job={{ ...runningJob, status: "completed", message: "エクスポートが完了しました。", destinationPath: "/tmp/export", artifactCount: 102 }} onClose={onClose} onStart={vi.fn()} onCancel={onCancel} />);

  expect(screen.getByRole("heading", { name: "エクスポート結果" })).toBeInTheDocument();
  expect(screen.getByText("下記フォルダにファイルを保存しました。")).toBeInTheDocument();
  expect(screen.queryByText("必要な成果物をまとめて設定します。")).not.toBeInTheDocument();
  expect(screen.getByText("/tmp/export")).toBeInTheDocument();
  expect(screen.queryByText(/生成数:/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "閉じる" })).toBeEnabled();

  rerender(
    <ExportDialog
      project={project}
      job={{
        ...runningJob,
        status: "completed_with_warnings",
        message: "一部の口パクLABを生成できませんでした。",
        destinationPath: "/tmp/export",
        artifactCount: 101,
        labFailures: [{ lineId: "line", lineNumber: 1, reason: "解析失敗" }],
      }}
      onClose={onClose}
      onStart={vi.fn()}
      onCancel={onCancel}
    />,
  );
  expect(screen.getByRole("heading", { name: "エクスポート結果" })).toBeInTheDocument();
  expect(screen.getByText("生成できなかった口パクLAB: 1件")).toBeInTheDocument();
});
