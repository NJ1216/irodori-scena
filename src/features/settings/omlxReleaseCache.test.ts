import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
vi.mock("../../api", () => ({ api: { omlxReleases: vi.fn() } }));
beforeEach(() => {
  vi.resetModules();
  vi.mocked(api.omlxReleases).mockReset();
});

it("shares concurrent reads and caches successful releases across dialog openings", async () => {
  vi.mocked(api.omlxReleases).mockResolvedValue({ repository: "jundot/omlx", releases: [] });
  const { cachedOmlxReleases } = await import("./omlxReleaseCache");
  const first = cachedOmlxReleases();
  expect(cachedOmlxReleases()).toBe(first);
  await first;
  await cachedOmlxReleases();
  expect(api.omlxReleases).toHaveBeenCalledTimes(1);
});

it("does not cache failed requests", async () => {
  vi.mocked(api.omlxReleases).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ repository: "jundot/omlx", releases: [] });
  const { cachedOmlxReleases } = await import("./omlxReleaseCache");
  await expect(cachedOmlxReleases()).rejects.toThrow("offline");
  await cachedOmlxReleases();
  expect(api.omlxReleases).toHaveBeenCalledTimes(2);
});
