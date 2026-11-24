import { api } from "../../api";

type Releases = Awaited<ReturnType<typeof api.omlxReleases>>["releases"];
let cache: { values: Releases; expiresAt: number } | null = null;
let pending: Promise<Releases> | null = null;

export function cachedOmlxReleases(): Promise<Releases> {
  if (cache && cache.expiresAt > Date.now()) return Promise.resolve(cache.values);
  if (!pending) {
    pending = api
      .omlxReleases()
      .then((result) => {
        cache = { values: result.releases, expiresAt: Date.now() + 5 * 60_000 };
        return result.releases;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}
