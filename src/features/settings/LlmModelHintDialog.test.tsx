// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { openExternal } from "../../api";
import { LlmModelHintDialog } from "./LlmModelHintDialog";

vi.mock("../../api", () => ({ openExternal: vi.fn() }));

it("explains the external-service boundary and the recommended Ollama Cloud setup", () => {
  const close = vi.fn();
  render(<LlmModelHintDialog onClose={close} />);
  expect(screen.getByRole("heading", { name: "LLMモデルを使うヒント" })).toBeInTheDocument();
  expect(screen.getByText(/PC単体では動かしにくい大規模モデル/)).toBeInTheDocument();
  const freeTier = screen.getByRole("note", { name: "Ollamaの無料利用枠" });
  expect(within(freeTier).getByText("無料枠で、SCENAの便利なLLM機能をしっかり試せます")).toBeInTheDocument();
  expect(screen.getByText(/毎月更新されるスターター利用枠/)).toBeInTheDocument();
  expect(within(freeTier).getByText("台本の作成・書き直し")).toBeInTheDocument();
  expect(within(freeTier).getByText("台詞の演出やキャスト設定の提案")).toBeInTheDocument();
  expect(within(freeTier).getByText("Voice Designの相談")).toBeInTheDocument();
  expect(within(freeTier).getByText(/実際に使える回数は/)).toBeInTheDocument();
  expect(screen.getByText("SCENAとは別の外部サービスです")).toBeInTheDocument();
  expect(screen.getByText(/台本や指示がOllamaのサービスへ送信/)).toBeInTheDocument();
  expect(screen.getAllByText("gemma4:31b-cloud")).toHaveLength(2);
  expect(screen.queryByText(/ollama run/)).not.toBeInTheDocument();
  expect(screen.getByText(/「API Keyを設定（任意）」はオフのままで構いません/)).toBeInTheDocument();
  expect(screen.getByText(/モデル欄へ/)).toBeInTheDocument();
  expect(screen.getAllByRole("img")).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "Ollamaの登録画面を拡大表示" }));
  const previewDialog = screen.getByRole("dialog", { name: "Ollamaの登録画面" });
  expect(previewDialog).toBeInTheDocument();
  expect(screen.getAllByRole("img")).toHaveLength(4);
  expect(within(previewDialog).queryByRole("button", { name: /^閉じる$/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "画像を閉じる" }));
  expect(screen.queryByRole("dialog", { name: "Ollamaの登録画面" })).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "LLMモデルを使うヒント" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ollamaをダウンロード" }));
  expect(openExternal).toHaveBeenCalledWith("https://ollama.com/download");
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(close).toHaveBeenCalledOnce();
});
