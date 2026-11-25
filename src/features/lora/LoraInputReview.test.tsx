import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LoraInputReview } from "./LoraInputReview";
import { useLoraTraining } from "./useLoraTraining";
import type { LoraInputRow } from "../../types/lora";
const { api, player } = vi.hoisted(() => ({ api: { status: vi.fn(async () => ({ supported: true })), jobs: vi.fn(async () => []), folderInputs: vi.fn() }, player: { setSource: vi.fn(), play: vi.fn(), stop: vi.fn(), dispose: vi.fn(), setCallbacks: vi.fn(), created: vi.fn() } }));
vi.mock("../../api-lora", () => ({ loraApi: api }));
vi.mock("../../api-core", () => ({ chooseDirectory: vi.fn(async () => "/fixture/100-pairs") }));
vi.mock("../shared/decodedAudioPlayer", () => ({
  DecodedAudioPlayer: class {
    callbacks: { onPlay?: () => void } = {};
    constructor() {
      player.created();
    }
    setCallbacks(callbacks: { onPlay?: () => void }) {
      this.callbacks = callbacks;
      player.setCallbacks(callbacks);
    }
    setSource = player.setSource;
    stop = player.stop;
    dispose = player.dispose;
    async play() {
      player.play();
      this.callbacks.onPlay?.();
    }
  },
}));
function rows(): LoraInputRow[] {
  return Array.from({ length: 100 }, (_, index) => ({ id: `internal-${index}`, wavName: `${index}.wav`, textName: `${index}.txt`, relativePath: `folder-${index % 2}/${index}.wav`, audioUrl: `/preview/${index}`, text: `台詞${index}`, caption: "", speakerId: "speaker-1", durationSeconds: 6, issues: [] }));
}
beforeEach(() => {
  vi.clearAllMocks();
  player.setSource.mockResolvedValue(true);
  api.folderInputs.mockResolvedValue({ datasetId: "data", rows: rows(), folderName: "100-pairs", ignoredTextCount: 2 });
});
function Harness() {
  const model = useLoraTraining();
  return (
    <>
      <button type="button" onClick={() => void model.importFolder()}>
        取り込み
      </button>
      <LoraInputReview model={model} />
    </>
  );
}
// Role queries over the whole 100-row table cost ~20x more than within one row; scope them to keep the suite fast under load.
function rowOf(label: string) {
  const row = screen.getByTitle(label).closest("tr");
  if (!row) throw new Error(`No table row for ${label}`);
  return within(row);
}
function editorOf(label: string) {
  const editor = screen.getByTitle(label).closest("tr")?.nextElementSibling;
  if (!(editor instanceof HTMLElement)) throw new Error(`No open editor for ${label}`);
  return within(editor);
}
async function loaded() {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "取り込み" }));
  await screen.findByTitle("folder-0/0.wav");
  expect(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを確認" })).toBeVisible();
}
it("shows 100 compact rows with no eager audio loading or per-row textareas and hides internal IDs", async () => {
  await loaded();
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("row")).toHaveLength(101);
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent),
  ).toEqual(["ファイル", "台詞", "再生", "状態", "除外"]);
  expect(screen.queryByLabelText("台詞")).not.toBeInTheDocument();
  expect(screen.queryByText("internal-0")).not.toBeInTheDocument();
  expect(screen.getByText(/100件・学習対象 100件・要確認 0件/)).toBeVisible();
  expect(screen.getByText(/TXT 2件/)).toBeVisible();
  expect(player.created).toHaveBeenCalledOnce();
  expect(player.setSource).not.toHaveBeenCalled();
});
it("edits only the selected row and preserves long transcript/caption drafts while switching rows", async () => {
  const data = rows();
  const text = "とても長い台詞\n".repeat(300);
  data[0].text = text;
  api.folderInputs.mockResolvedValue({ datasetId: "data", rows: data });
  await loaded();
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavの台詞を編集" }));
  expect(editorOf("folder-0/0.wav").getByLabelText("台詞")).toHaveValue(text);
  fireEvent.change(editorOf("folder-0/0.wav").getByLabelText("台詞"), { target: { value: "-途中の台詞" } });
  fireEvent.change(editorOf("folder-0/0.wav").getByLabelText("声・話し方の説明"), { target: { value: "声の説明" } });
  fireEvent.click(rowOf("folder-1/1.wav").getByRole("button", { name: "folder-1/1.wavの台詞を編集" }));
  expect(screen.getAllByLabelText("台詞")).toHaveLength(1);
  expect(editorOf("folder-1/1.wav").getByLabelText("台詞")).toHaveValue("台詞1");
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを確認" }));
  expect(editorOf("folder-0/0.wav").getByLabelText("台詞")).toHaveValue("-途中の台詞");
  expect(editorOf("folder-0/0.wav").getByLabelText("声・話し方の説明")).toHaveValue("声の説明");
});
it("shows missing TXT and warnings inline, allows explicit transcript repair and exclusion without rewriting other rows", async () => {
  const data = rows();
  data[0] = { ...data[0], textName: null, text: "", issues: ["TXTがありません。本文を入力してください。"] };
  data[1].issues = ["音声の検査警告"];
  api.folderInputs.mockResolvedValue({ datasetId: "data", rows: data });
  await loaded();
  expect(screen.getByText("台詞なし")).toBeVisible();
  expect(screen.getByText("要確認")).toBeVisible();
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを確認" }));
  expect(screen.getByRole("alert")).toHaveTextContent("TXTがありません");
  fireEvent.change(editorOf("folder-0/0.wav").getByLabelText("台詞"), { target: { value: "手入力の台詞" } });
  expect(screen.getByText("手入力済み")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(rowOf("folder-1/1.wav").getByRole("checkbox", { name: "folder-1/1.wavを除外" }));
  expect(rowOf("folder-1/1.wav").getByRole("button", { name: "folder-1/1.wavを確認" }).closest("tr")).toHaveTextContent("除外");
  expect(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavの台詞を編集" })).toHaveTextContent("手入力の台詞");
});
it("keeps ambiguous pairing blocked despite valid transcript text and allows only explicit exclusion or reimport", async () => {
  const data = rows();
  data[0] = { ...data[0], blocked: true, issues: ["同名候補が複数あります。"] };
  api.folderInputs.mockResolvedValue({ datasetId: "data", rows: data });
  await loaded();
  expect(screen.getByText("対応を確認")).toBeVisible();
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを確認" }));
  expect(editorOf("folder-0/0.wav").getByLabelText("台詞")).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("同名候補");
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("checkbox", { name: "folder-0/0.wavを除外" }));
  expect(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを確認" }).closest("tr")).toHaveTextContent("除外");
});
it("fetches only the selected preview and prevents an older slow load from starting after another row", async () => {
  await loaded();
  let release!: (ready: boolean) => void;
  player.setSource
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    )
    .mockResolvedValue(true);
  fireEvent.click(rowOf("folder-0/0.wav").getByRole("button", { name: "folder-0/0.wavを再生" }));
  fireEvent.click(rowOf("folder-1/1.wav").getByRole("button", { name: "folder-1/1.wavを再生" }));
  await waitFor(() => expect(player.play).toHaveBeenCalledOnce());
  await act(async () => {
    release(true);
  });
  expect(player.play).toHaveBeenCalledOnce();
  expect(player.setSource.mock.calls).toEqual([["/preview/0"], ["/preview/1"]]);
  expect(rowOf("folder-1/1.wav").getByRole("button", { name: "folder-1/1.wavを停止" })).toBeVisible();
});
it("reports preview failures and disposes the one player when review closes", async () => {
  const view = render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "取り込み" }));
  await screen.findByTitle("folder-0/0.wav");
  act(() => {
    player.setCallbacks.mock.calls[0][0].onError(new Error("broken"));
  });
  expect(screen.getByRole("alert")).toHaveTextContent("音声を再生できません");
  view.unmount();
  expect(player.dispose).toHaveBeenCalledOnce();
});
