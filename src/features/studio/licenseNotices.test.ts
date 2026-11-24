import { afterEach, expect, it, vi } from "vitest";
import { loadLicenseNotices } from "./licenseNotices";

afterEach(() => vi.unstubAllGlobals());
it("decodes gzip without losing Unicode or whitespace and accepts HTTP-decoded bytes", async () => {
  const value = { applicationLicense: "著作権\n  exact text\r\n", entries: [], texts: {} };
  const plain = new TextEncoder().encode(JSON.stringify(value));
  const compressed = Uint8Array.from(atob("H4sIAAAAAAAC/6tWSiwoyMlMTizJzM/zyUxOzStOVbJSUHoxcfqTvXOerVgZk6egkFqRmFyiUJJaURJTFJOnpKOglJpXUpSZWgxUGR0L5IKkQJzq2loA6lLfPlEAAAA="), (character) => character.charCodeAt(0));
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  for (const bytes of [compressed, plain]) {
    fetcher.mockResolvedValueOnce({ ok: true, arrayBuffer: async () => Uint8Array.from(bytes).buffer });
    expect(await loadLicenseNotices(new AbortController().signal)).toEqual(value);
  }
  expect(fetcher.mock.calls[0][0]).toBe("/third-party-licenses.json.gz");
});
it("rejects truncated compressed content and aborted loads", async () => {
  const bytes = Uint8Array.from(atob("H4sIAAAAAAAC/6uuBQBDv6ajAgAAAA=="), (character) => character.charCodeAt(0));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => Uint8Array.from(bytes.subarray(0, 12)).buffer }));
  await expect(loadLicenseNotices(new AbortController().signal)).rejects.toThrow();
  const controller = new AbortController();
  controller.abort();
  await expect(loadLicenseNotices(controller.signal)).rejects.toThrow();
});
