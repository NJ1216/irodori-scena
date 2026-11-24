import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { RhubarbStatus } from "../../types";
import { RhubarbStartupUpdate } from "./RhubarbStartupUpdate";

vi.mock("../../api", () => ({ api: { rhubarbStatus: vi.fn(), installRhubarb: vi.fn() }, openExternal: vi.fn() }));
const update = { installed: true, available: true, updateAvailable: true, ready: true, supported: true, version: "1.14.0-scena.2", license: "MIT" } as RhubarbStatus;
beforeEach(() => {
  vi.mocked(api.rhubarbStatus).mockResolvedValue(update);
});
afterEach(() => {
  vi.clearAllMocks();
});

it("waits for another dialog, then offers update without downloading and dismisses for this session", async () => {
  const view = render(
    <>
      <section role="dialog">Setup</section>
      <RhubarbStartupUpdate />
    </>,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 150));
  });
  expect(screen.queryByText("後で")).toBeNull();
  view.rerender(<RhubarbStartupUpdate />);
  fireEvent.click(await screen.findByText("後で"));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 150));
  });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(api.installRhubarb).not.toHaveBeenCalled();
});

it.each([
  { ...update, installed: false },
  { ...update, updateAvailable: false },
  { ...update, available: false },
])("does not offer unavailable or unnecessary updates", async (status) => {
  vi.mocked(api.rhubarbStatus).mockResolvedValue(status);
  render(<RhubarbStartupUpdate />);
  await waitFor(() => expect(api.rhubarbStatus).toHaveBeenCalled());
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("ignores failed checks", async () => {
  vi.mocked(api.rhubarbStatus).mockRejectedValue(new Error("offline"));
  render(<RhubarbStartupUpdate />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.queryByRole("dialog")).toBeNull();
});

it.each(["modal-backdrop", "studio-loading"])("waits for %s before presenting", async (kind) => {
  const blocker = document.createElement("div");
  if (kind === "modal-backdrop") blocker.className = "modal-backdrop";
  else blocker.setAttribute("data-studio-dialog-loading", "");
  document.body.append(blocker);
  render(<RhubarbStartupUpdate />);
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 150));
  });
  expect(screen.queryByText("後で")).toBeNull();
  blocker.remove();
  expect(await screen.findByText("後で")).toBeInTheDocument();
});
