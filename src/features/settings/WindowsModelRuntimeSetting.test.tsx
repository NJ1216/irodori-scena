// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { LlmCard } from "../../types";
import { ModelRuntimeSetting } from "./ModelRuntimeSetting";
import { LlmCardTestControls } from "./LlmCardTestControls";

function WindowsModelRuntimeSetting({ card, onRefresh }: { card: LlmCard; onRefresh: () => void }) {
  return (
    <>
      <ModelRuntimeSetting card={card} onRefresh={onRefresh} />
      <LlmCardTestControls card={card} cardId={card.id} disabled onStatus={vi.fn()} onComplete={onRefresh} />
    </>
  );
}

vi.mock("../shared/platform", () => ({ isWindows: () => true }));

afterEach(() => vi.restoreAllMocks());
const card = { id: "downloaded", source: "managed", runtime: { state: "missing", job: { state: "failed", message: "LICENSE missing" } } } as LlmCard;

it("shows the failure and resumes preparation of the downloaded card", async () => {
  const prepare = vi.spyOn(api, "prepareModelRuntime").mockResolvedValue({});
  const refresh = vi.fn();
  const { rerender } = render(<WindowsModelRuntimeSetting card={card} onRefresh={refresh} />);
  expect(screen.getByRole("status")).toHaveTextContent("LICENSE missing");
  expect(screen.getAllByRole("button")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "基本動作を確認" }));
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  expect(prepare).toHaveBeenCalledWith("downloaded", {});
  const ready = { ...card, runtime: { ...card.runtime!, state: "ready", job: null } };
  rerender(<WindowsModelRuntimeSetting card={ready} onRefresh={refresh} />);
  expect(screen.getByRole("button", { name: "基本動作を確認" })).toBeEnabled();
});

it("keeps one confirmation control and offers cancellation while preparing", async () => {
  const cancel = vi.spyOn(api, "cancelModelRuntime").mockResolvedValue({});
  const busy = { ...card, runtime: { ...card.runtime!, job: { ...card.runtime!.job!, state: "preparing" } } };
  render(<WindowsModelRuntimeSetting card={busy} onRefresh={vi.fn()} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "確認を取り消す" }));
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(card.id));
});

it("reports retry failure without hiding the recovery action", async () => {
  vi.spyOn(api, "prepareModelRuntime").mockRejectedValue(new Error("offline"));
  render(<WindowsModelRuntimeSetting card={card} onRefresh={vi.fn()} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  expect(screen.getByRole("button")).toBeEnabled();
});
