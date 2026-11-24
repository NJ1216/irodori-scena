// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";

vi.mock("../shared/platform", () => ({ isWindows: () => true }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("defaults each submitted search to downloads, switches ranking, and preserves filters", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [] });
  const model = { repoId: "org/model", publisher: "org", revision: "fixed", displayName: "Model", downloads: 10, gated: false, compatibility: "gguf" as const, warning: null, downloadSizeBytes: 7e9, inferredTags: [] };
  const search = vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [model] });
  render(<BuiltInLlmDialog onAdded={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  expect(screen.queryByRole("group", { name: "並び順" })).toBeNull();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  const order = within(screen.getByRole("group", { name: "並び順" }));
  expect(order.getByRole("button", { name: "DL順" })).toHaveAttribute("aria-pressed", "true");
  expect(search).toHaveBeenLastCalledWith("", [], "downloads");
  fireEvent.click(screen.getByRole("button", { name: "8GB" }));
  await act(async () => {
    fireEvent.click(order.getByRole("button", { name: "人気順" }));
  });
  expect(search).toHaveBeenLastCalledWith("", [], "likes");
  expect(order.getAllByRole("button", { pressed: true })).toHaveLength(1);
  expect(screen.getByRole("button", { name: "8GB" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(screen.getByRole("group", { name: "提供元" })).getByRole("button", { name: "org" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(search).toHaveBeenLastCalledWith("", ["publisher:org"], "likes");
  await act(async () => {
    fireEvent.click(order.getByRole("button", { name: "名前順" }));
  });
  expect(search).toHaveBeenLastCalledWith("", ["publisher:org"], "name");
  await act(async () => {
    fireEvent.click(order.getByRole("button", { name: "名前順" }));
  });
  expect(order.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  expect(search).toHaveBeenLastCalledWith("", ["publisher:org"], "default");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  expect(order.getByRole("button", { name: "DL順" })).toHaveAttribute("aria-pressed", "true");
  expect(search).toHaveBeenLastCalledWith("", [], "downloads");
});
