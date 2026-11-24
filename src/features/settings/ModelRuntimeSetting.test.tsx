// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { LlmCard, OmlxRuntimeStatus } from "../../types";
import { cachedOmlxReleases } from "./omlxReleaseCache";
import { ModelRuntimeSetting } from "./ModelRuntimeSetting";

vi.mock("./omlxReleaseCache", () => ({ cachedOmlxReleases: vi.fn() }));
const card = {
  id: "one",
  runtimeId: "old",
  source: "managed",
  runtime: {
    state: "ready",
    version: "0.6.3",
    runtimeId: "old",
    recommended: false,
    job: null,
  },
} as LlmCard;
const status = { recommendedRuntimeId: "new", installedRuntimes: [{ id: "old", omlxVersion: "0.6.3", state: "ready" }], catalog: [{ id: "new", omlxVersion: "0.6.4" }] } as unknown as OmlxRuntimeStatus;
beforeEach(() => {
  vi.spyOn(api, "omlxRuntimes").mockResolvedValue(status);
  vi.mocked(cachedOmlxReleases).mockResolvedValue([{ tag: "v1", name: "v1", prerelease: false, publishedAt: null }]);
});
afterEach(() => vi.restoreAllMocks());

it("automatically loads releases and keeps the ordinary surface to one selector", async () => {
  render(<ModelRuntimeSetting card={card} onRefresh={vi.fn()} />);
  await screen.findByRole("option", { name: "oMLX v1 · 公開版" });
  expect(cachedOmlxReleases).toHaveBeenCalled();
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText("old", { exact: true })).toBeNull();
});

it("confirms downloads on selection and preserves the current version when cancelled", async () => {
  const prepare = vi.spyOn(api, "prepareModelRuntime").mockResolvedValue({});
  render(<ModelRuntimeSetting card={card} onRefresh={vi.fn()} />);
  await screen.findByRole("option", { name: "oMLX v1 · 公開版" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "release:v1" } });
  const dialog = within(screen.getByRole("dialog", { name: "oMLX v1を取得しますか？" }));
  expect(dialog.getByText(/SCENA未検証/)).toBeInTheDocument();
  expect(prepare).not.toHaveBeenCalled();
  fireEvent.click(dialog.getByRole("button", { name: "キャンセル" }));
  expect(screen.getByRole("combobox")).toHaveValue("old");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("downloads only after confirmation and reverts the selection on failure", async () => {
  const prepare = vi.spyOn(api, "prepareModelRuntime").mockRejectedValue(new Error("取得できませんでした"));
  render(<ModelRuntimeSetting card={card} onRefresh={vi.fn()} />);
  await screen.findByRole("option", { name: "oMLX v1 · 公開版" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "release:v1" } });
  fireEvent.click(screen.getByRole("button", { name: "取得" }));
  expect(prepare).toHaveBeenCalledWith("one", { tag: "v1" });
  expect(await screen.findByRole("alert")).toHaveTextContent("取得できませんでした");
  expect(screen.getByRole("combobox")).toHaveValue("old");
});

it("shows a missing bound runtime and resumes it through the same selector", async () => {
  const missing = { ...card, runtime: { ...card.runtime!, state: "missing" } };
  vi.spyOn(api, "omlxRuntimes").mockResolvedValue({ ...status, installedRuntimes: [{ ...status.installedRuntimes[0], state: "missing" }] });
  const prepare = vi.spyOn(api, "prepareModelRuntime").mockResolvedValue({});
  render(<ModelRuntimeSetting card={missing} onRefresh={vi.fn()} />);
  const selector = await screen.findByRole("combobox");
  expect(selector).toHaveValue("bound:old");
  expect(screen.getByRole("option", { name: "oMLX 0.6.3 · 準備が必要（設定済み）" })).toBeInTheDocument();
  fireEvent.change(selector, { target: { value: "old" } });
  const dialog = within(screen.getByRole("dialog", { name: "oMLX 0.6.3を取得しますか？" }));
  fireEvent.click(dialog.getByRole("button", { name: "取得" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledWith("one", { runtimeId: "old" }));
});

it("checks an installed version directly and changes selection only after backend success", async () => {
  vi.spyOn(api, "omlxRuntimes").mockResolvedValue({ ...status, installedRuntimes: [...status.installedRuntimes, { ...status.installedRuntimes[0], id: "new", omlxVersion: "0.6.4", state: "ready" }] });
  const prepare = vi.spyOn(api, "prepareModelRuntime").mockResolvedValue({});
  const { rerender } = render(<ModelRuntimeSetting card={card} onRefresh={vi.fn()} />);
  await screen.findByRole("option", { name: /SCENA検証済み/ });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "new" } });
  await waitFor(() => expect(prepare).toHaveBeenCalledWith("one", { runtimeId: "new" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("combobox")).toHaveValue("old");
  rerender(<ModelRuntimeSetting card={{ ...card, runtimeId: "new" }} onRefresh={vi.fn()} />);
  expect(screen.getByRole("combobox")).toHaveValue("new");
});

it("offers cancellation only while preparing", () => {
  const cancel = vi.spyOn(api, "cancelModelRuntime").mockResolvedValue({});
  const preparing = { ...card, runtime: { ...card.runtime!, job: { id: "job", runtimeId: "old", state: "preparing", message: "取得中" } } };
  render(<ModelRuntimeSetting card={preparing} onRefresh={vi.fn()} />);
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.getAllByRole("button")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(cancel).toHaveBeenCalledWith("one");
});
