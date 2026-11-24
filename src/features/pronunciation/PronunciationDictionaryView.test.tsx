import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, HISTORY_APPLIED_EVENT } from "../../api";
import { PronunciationDictionaryView } from "./PronunciationDictionaryView";

vi.mock("./CastDictionaryTable", () => ({ CastDictionaryTable: () => null }));
vi.mock("./ManualDictionaryTable", () => ({
  ManualDictionaryTable: ({ onAdd, onToggleScope }: { onAdd: (term: string, reading: string) => Promise<void>; onToggleScope: (entry: object, scope: "global", enabled: boolean) => Promise<void> }) => (
    <>
      <button data-testid="add-dictionary" onClick={() => void onAdd("Tokyo", "とうきょう")}>
        辞書変更
      </button>
      <button onClick={() => void onToggleScope({ id: "manual-1", globalId: "global-1", source: "manual", term: "東京", reading: "とうきょう" }, "global", false)}>SCENAタグを外す</button>
      <button onClick={() => void onToggleScope({ id: "manual-2", globalId: "global-2", projectId: "project-2", scopes: ["global", "project"], source: "manual", term: "大阪", reading: "おおさか" }, "global", false)}>両方ある行のSCENAタグを外す</button>
    </>
  ),
}));
vi.mock("../../api", () => ({
  HISTORY_APPLIED_EVENT: "test-history-applied",
  api: {
    pronunciationDictionary: vi.fn(),
    changePronunciationDictionary: vi.fn(),
  },
}));

describe("PronunciationDictionaryView regeneration confirmation", () => {
  beforeEach(() => {
    vi.mocked(api.pronunciationDictionary).mockReset();
    vi.mocked(api.changePronunciationDictionary).mockReset();
    vi.mocked(api.pronunciationDictionary).mockResolvedValue([]);
    vi.mocked(api.changePronunciationDictionary).mockResolvedValue({
      entries: [],
      affectedLineIds: ["line-1", "line-2"],
    });
  });

  it("defaults to a new take and keeps the saved dictionary when dismissed", async () => {
    const regenerate = vi.fn();
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={regenerate} />);
    fireEvent.click(await screen.findByText("辞書変更"));
    expect(await screen.findByRole("dialog")).toHaveTextContent("2行の読みが変わります");
    expect(screen.getByLabelText("新規テイクとして追加（推奨）")).toBeChecked();
    fireEvent.click(screen.getByText("再生成しない"));
    expect(regenerate).not.toHaveBeenCalled();
    expect(api.changePronunciationDictionary).toHaveBeenCalledTimes(1);
  });

  it("passes the chosen overwrite mode", async () => {
    const regenerate = vi.fn().mockResolvedValue(undefined);
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={regenerate} />);
    fireEvent.click(await screen.findByText("辞書変更"));
    fireEvent.click(await screen.findByLabelText("選択テイクを上書き"));
    fireEvent.click(screen.getByText("再生成する"));
    await waitFor(() => expect(regenerate).toHaveBeenCalledWith(["line-1", "line-2"], "replace"));
  });

  it("does not remove a scope until the deletion is confirmed", async () => {
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={vi.fn()} />);
    fireEvent.click(await screen.findByText("SCENAタグを外す"));
    expect(await screen.findByRole("dialog")).toHaveTextContent("SCENAから「東京」を削除しますか？");
    expect(api.changePronunciationDictionary).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("キャンセル"));
    expect(api.changePronunciationDictionary).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("SCENAタグを外す"));
    fireEvent.click(await screen.findByText("SCENAから削除"));
    await waitFor(() => expect(api.changePronunciationDictionary).toHaveBeenCalledWith(expect.objectContaining({ operation: "toggle-scope", scope: "global", enabled: false })));
  });

  it("removes one of two active scopes without a deletion confirmation", async () => {
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={vi.fn()} />);
    fireEvent.click(await screen.findByText("両方ある行のSCENAタグを外す"));
    await waitFor(() => expect(api.changePronunciationDictionary).toHaveBeenCalledWith(expect.objectContaining({ operation: "toggle-scope", scope: "global", enabled: false })));
    expect(screen.queryByText("SCENAから「大阪」を削除しますか？")).not.toBeInTheDocument();
  });

  it("reloads dictionary entries after pronunciation history is applied", async () => {
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={vi.fn()} />);
    await waitFor(() => expect(api.pronunciationDictionary).toHaveBeenCalled());
    const calls = vi.mocked(api.pronunciationDictionary).mock.calls.length;
    window.dispatchEvent(new CustomEvent(HISTORY_APPLIED_EVENT, { detail: "pronunciation" }));
    await waitFor(() => expect(vi.mocked(api.pronunciationDictionary).mock.calls.length).toBeGreaterThan(calls));
  });

  it("sends dictionary edits in click order", async () => {
    let finishFirst: ((value: { entries: []; affectedLineIds: [] }) => void) | undefined;
    vi.mocked(api.changePronunciationDictionary).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    );
    render(<PronunciationDictionaryView characters={[]} onNotice={vi.fn()} onRegenerate={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("add-dictionary"));
    fireEvent.click(screen.getByTestId("add-dictionary"));
    await waitFor(() => expect(api.changePronunciationDictionary).toHaveBeenCalledTimes(1));
    finishFirst?.({ entries: [], affectedLineIds: [] });
    await waitFor(() => expect(api.changePronunciationDictionary).toHaveBeenCalledTimes(2));
  });
});
