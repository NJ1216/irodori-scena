import { useRef } from "react";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { useCastDeletion } from "./useCastDeletion";
import { captureCastSnapshot, castSnapshotTimeoutMs } from "./castSnapshot";
import { particleDeletionDiagnostics } from "../shared/particleDeletionDiagnostics";
import { cancelDestructiveConfirmation, confirmDestructiveAction } from "../shared/destructiveConfirmation";
import { DestructiveConfirmationNotice } from "../shared/DestructiveConfirmationNotice";
import { CastDeletionFeedback } from "./CastDeletionFeedback";

vi.mock("./castSnapshot", () => ({ captureCastSnapshot: vi.fn(), castSnapshotTimeoutMs: 800, disposeCastSnapshot: vi.fn() }));
const cast = { id: "one", name: "彩" } as Character;
const region = document.createElement("div");
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
});
afterEach(() => {
  cancelDestructiveConfirmation();
  vi.useRealTimers();
});

it("starts preparation on the first click and waits for it before a rapid confirmed deletion", async () => {
  const image = { canvas: document.createElement("canvas"), width: 100, height: 100, left: 0, top: 0 };
  let finish!: (value: typeof image) => void;
  vi.mocked(captureCastSnapshot).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  let confirmed = false;
  const persisted = vi.fn();
  const remove = vi.fn(async (_character, beforeDelete) => {
    if (!confirmed) {
      confirmed = true;
      return false;
    }
    await beforeDelete?.();
    persisted();
    return true;
  });
  const { result } = renderHook(() => useCastDeletion([cast], remove));
  await act(() => result.current.remove(cast, region));
  expect(captureCastSnapshot).toHaveBeenCalledOnce();
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.remove(cast, region);
  });
  expect(persisted).not.toHaveBeenCalled();
  await act(async () => {
    finish(image);
    await pending;
  });
  expect(captureCastSnapshot).toHaveBeenCalledOnce();
  expect(persisted).toHaveBeenCalledOnce();
  expect(result.current.deletion).toMatchObject({ phase: "dissolving", image });
  act(() => vi.advanceTimersByTime(2000));
  expect(result.current.deletion).toBeNull();
});

it("confirms deletion with a DOM fallback when particles cannot be prepared", async () => {
  vi.mocked(captureCastSnapshot).mockRejectedValue(new Error("image unavailable"));
  const persisted = vi.fn();
  const remove = vi.fn(async (_character, beforeDelete) => {
    try {
      await beforeDelete?.();
    } catch {
      return false;
    }
    persisted();
    return true;
  });
  const { result } = renderHook(() => useCastDeletion([cast], remove));
  await act(() => result.current.remove(cast, region));
  expect(persisted).toHaveBeenCalledOnce();
  expect(result.current.deletion).toMatchObject({ phase: "dissolving", image: null });
  expect(result.current.characters).toEqual([cast]);
  expect(particleDeletionDiagnostics().at(-1)).toMatchObject({ target: "cast", itemId: "one", phase: "unknown", outcome: "failed", error: "Error: image unavailable" });
});

it("accepts the second delete click even when the snapshot has failed", async () => {
  vi.mocked(captureCastSnapshot).mockRejectedValue(new Error("transparent capture"));
  const persisted = vi.fn();
  const remove = async (_character: Character, beforeDelete?: () => Promise<void>) => {
    if (!confirmDestructiveAction("delete-character-one", vi.fn(), "削除します")) return false;
    await beforeDelete?.();
    persisted();
    return true;
  };
  const { result } = renderHook(() => useCastDeletion([cast], remove));
  await act(() => result.current.remove(cast, region));
  expect(persisted).not.toHaveBeenCalled();
  await act(() => result.current.remove(cast, region));
  expect(persisted).toHaveBeenCalledOnce();
  expect(result.current.deletion).toMatchObject({ phase: "dissolving", image: null });
});

it("keeps the delete control interactive until the second confirmation click", async () => {
  vi.useRealTimers();
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(captureCastSnapshot).mockRejectedValue(new Error("capture unavailable"));
  const persisted = vi.fn();
  const remove = async (_character: Character, beforeDelete?: () => Promise<void>) => {
    if (!confirmDestructiveAction("delete-character-one", vi.fn(), "削除します")) return false;
    await beforeDelete?.();
    persisted();
    return true;
  };
  function Harness() {
    const regionRef = useRef<HTMLDivElement>(null);
    const deletion = useCastDeletion([cast], remove);
    return (
      <>
        <DestructiveConfirmationNotice />
        <CastDeletionFeedback deletion={deletion.deletion} regionRef={regionRef}>
          <div className="cast-notebook-spread">
            <div className="cast-notebook-page">
              <button type="button" data-destructive-confirmation-key="delete-character-one" onClick={() => void deletion.remove(cast, regionRef.current)}>
                削除
              </button>
            </div>
          </div>
        </CastDeletionFeedback>
      </>
    );
  }
  render(<Harness />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "削除" }));
  expect(screen.getByRole("status")).toHaveTextContent("4秒以内");
  expect(screen.getByRole("button", { name: "削除" }).closest("[inert]")).toBeNull();
  expect(persisted).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "削除" }));
  expect(persisted).toHaveBeenCalledOnce();
  expect(screen.getByRole("status")).toHaveTextContent("「彩」を削除しました");
});

it("completes a confirmed deletion after a bounded snapshot wait", async () => {
  vi.mocked(captureCastSnapshot).mockImplementation(() => new Promise(() => {}));
  const persisted = vi.fn();
  const remove = async (_character: Character, beforeDelete?: () => Promise<void>) => {
    if (!confirmDestructiveAction("delete-character-one", vi.fn(), "削除します")) return false;
    await beforeDelete?.();
    persisted();
    return true;
  };
  const { result } = renderHook(() => useCastDeletion([cast], remove));
  await act(() => result.current.remove(cast, region));
  let confirmed!: Promise<void>;
  act(() => {
    confirmed = result.current.remove(cast, region);
  });
  expect(persisted).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(castSnapshotTimeoutMs);
    await confirmed;
  });
  expect(persisted).toHaveBeenCalledOnce();
  expect(result.current.deletion).toMatchObject({ phase: "dissolving", image: null });
});

it("aborts preparation when the cast page unmounts", async () => {
  vi.mocked(captureCastSnapshot).mockImplementation(() => new Promise(() => {}));
  const { result, unmount } = renderHook(() => useCastDeletion([cast], async () => false));
  await act(() => result.current.remove(cast, region));
  const signal = vi.mocked(captureCastSnapshot).mock.calls[0][1];
  unmount();
  expect(signal.aborted).toBe(true);
});
