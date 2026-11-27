// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { LlamaCppRuntimeSetting } from "./LlamaCppRuntimeSetting";

afterEach(() => vi.restoreAllMocks());
const runtime = (backend: "cuda" | "cpu") => ({ backend, version: "b1", ready: true }) as Awaited<ReturnType<typeof api.llamaCppRuntime>>;

it("clears a failed refresh message once a later refresh succeeds", async () => {
  const read = vi.spyOn(api, "llamaCppRuntime").mockImplementation(async (backend) => runtime(backend ?? "cuda"));
  vi.spyOn(api, "deleteLlamaCppRuntime").mockResolvedValue({});
  render(<LlamaCppRuntimeSetting />);
  fireEvent.click(screen.getByRole("button", { name: "llama.cpp管理" }));
  await screen.findAllByRole("button", { name: "実行基盤を削除" });
  read.mockRejectedValue(new Error("再読み込み失敗"));
  fireEvent.click(screen.getAllByRole("button", { name: "実行基盤を削除" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "もう一度押して削除" }));
  expect(await screen.findByText("再読み込み失敗")).toBeInTheDocument();
  read.mockImplementation(async (backend) => runtime(backend ?? "cuda"));
  fireEvent.click(screen.getAllByRole("button", { name: "実行基盤を削除" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "もう一度押して削除" }));
  await vi.waitFor(() => expect(screen.queryByText("再読み込み失敗")).toBeNull());
});
