import { render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AudioPlaybackBar } from "./AudioPlaybackBar";
const { setSource, dispose, stop } = vi.hoisted(() => ({ setSource: vi.fn(), dispose: vi.fn(), stop: vi.fn() }));
vi.mock("../shared/decodedAudioPlayer", () => ({
  DecodedAudioPlayer: class {
    setCallbacks() {}
    setSource = setSource;
    dispose = dispose;
    stop = stop;
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
});
it.each([true, false])("reports decoded reference availability, ready=%s", async (ready) => {
  setSource.mockResolvedValue(ready);
  const report = vi.fn();
  render(<AudioPlaybackBar src="/reference" label="reference" onLoadState={report} />);
  expect(report).toHaveBeenCalledWith("loading");
  await waitFor(() => expect(report).toHaveBeenLastCalledWith(ready ? "ready" : "failed"));
});
it("does not fetch an empty source and ignores a late result from a previous reference", async () => {
  const report = vi.fn();
  let resolve!: (ready: boolean) => void;
  setSource.mockImplementation((url: string) =>
    url === ""
      ? Promise.resolve(false)
      : new Promise<boolean>((done) => {
          resolve = done;
        }),
  );
  const { rerender } = render(<AudioPlaybackBar src="/old" label="reference" onLoadState={report} />);
  rerender(<AudioPlaybackBar src="" label="reference" onLoadState={report} />);
  expect(report).toHaveBeenLastCalledWith("failed");
  resolve(true);
  await Promise.resolve();
  expect(report).toHaveBeenLastCalledWith("failed");
  expect(setSource).toHaveBeenCalledTimes(2);
  expect(setSource).toHaveBeenLastCalledWith("");
});
