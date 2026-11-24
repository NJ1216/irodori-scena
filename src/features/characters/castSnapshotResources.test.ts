import { afterEach, expect, it, vi } from "vitest";
import { apiConnection, apiFetch } from "../../api-runtime";
import { loadSnapshotSvg, rasterizeSnapshotSvg, snapshotImageUrl } from "./castSnapshotResources";

vi.mock("../../api-runtime", () => ({ apiConnection: vi.fn(async () => ({ baseUrl: "http://127.0.0.1:9876", token: "test-token" })), apiFetch: vi.fn() }));
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

it("rejects foreign image URLs without sending the local API credential", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(snapshotImageUrl("https://untrusted.example/image.png", new AbortController().signal)).rejects.toThrow("must belong");
  expect(fetch).not.toHaveBeenCalled();
  expect(apiFetch).not.toHaveBeenCalled();
});

it("uses authenticated API media and embeds it without an external URL", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, blob: async () => new Blob(["image"], { type: "image/png" }) } as Response);
  const signal = new AbortController().signal;
  expect(await snapshotImageUrl("http://127.0.0.1:9876/api/media/avatar.png", signal)).toMatch(/^data:image\/png;base64,/);
  expect(apiFetch).toHaveBeenCalledWith("http://127.0.0.1:9876/api/media/avatar.png", { signal, cache: "no-store" });
});

it("bypasses the image element cache for same-origin media snapshots", async () => {
  const fetchImage = vi.fn(async () => ({ ok: true, blob: async () => new Blob(["image"], { type: "image/png" }) }) as Response);
  vi.stubGlobal("fetch", fetchImage);
  const signal = new AbortController().signal;
  await snapshotImageUrl(`${location.origin}/avatar.png`, signal);
  expect(fetchImage).toHaveBeenCalledWith(new URL(`${location.origin}/avatar.png`), { signal, cache: "no-store" });
});

it("retains data images and propagates media failures to the optional-capture boundary", async () => {
  expect(await snapshotImageUrl("data:image/png;base64,dGVzdA==", new AbortController().signal)).toBe("data:image/png;base64,dGVzdA==");
  expect(apiConnection).not.toHaveBeenCalled();
  vi.mocked(apiFetch).mockResolvedValue({ ok: false } as Response);
  await expect(snapshotImageUrl("http://127.0.0.1:9876/api/media/missing.png", new AbortController().signal)).rejects.toThrow("could not be loaded");
});

it("cancels a pending SVG decode and releases its image source", async () => {
  const image = { src: "", onload: null, onerror: null };
  vi.stubGlobal(
    "Image",
    class {
      constructor() {
        return image;
      }
    },
  );
  const controller = new AbortController();
  const pending = loadSnapshotSvg("<svg/>", controller.signal);
  const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  await rejected;
  expect(image.src).toBe("");
  expect(image.onload).toBeNull();
});

it("falls back from a data URL to a blob URL and revokes it", async () => {
  const revoke = vi.fn();
  const NativeUrl = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeUrl {
      static createObjectURL = vi.fn(() => "blob:test");
      static revokeObjectURL = revoke;
    },
  );
  vi.stubGlobal(
    "Image",
    class {
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(value: string) {
        if (value) queueMicrotask(() => (value.startsWith("data:") ? this.onerror?.() : this.onload?.()));
      }
    },
  );
  const context = { clearRect: vi.fn(), drawImage: vi.fn(), getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) })) };
  const canvas = { width: 10, height: 10, getContext: vi.fn(() => context) } as unknown as HTMLCanvasElement;
  const failures = await rasterizeSnapshotSvg("<svg/>", canvas, new AbortController().signal);
  expect(failures.map((failure) => failure.stage)).toEqual(["data-url"]);
  expect(context.drawImage).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:test");
});

it("does not create a blob URL when the established data URL path succeeds", async () => {
  const create = vi.fn(() => "blob:unused");
  const NativeUrl = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeUrl {
      static createObjectURL = create;
      static revokeObjectURL = vi.fn();
    },
  );
  vi.stubGlobal(
    "Image",
    class {
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(value: string) {
        if (value) queueMicrotask(() => this.onload?.());
      }
    },
  );
  const context = { clearRect: vi.fn(), drawImage: vi.fn(), getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) })) };
  const canvas = { width: 10, height: 10, getContext: vi.fn(() => context) } as unknown as HTMLCanvasElement;
  expect(await rasterizeSnapshotSvg("<svg/>", canvas, new AbortController().signal)).toEqual([]);
  expect(create).not.toHaveBeenCalled();
});

it("retries a decoded but transparent WebView2 data URL through a blob URL", async () => {
  const NativeUrl = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeUrl {
      static createObjectURL = vi.fn(() => "blob:test");
      static revokeObjectURL = vi.fn();
    },
  );
  vi.stubGlobal(
    "Image",
    class {
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      currentSource = "";
      set src(value: string) {
        this.currentSource = value;
        if (value) queueMicrotask(() => this.onload?.());
      }
    },
  );
  const context = {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    getImageData: vi
      .fn()
      .mockReturnValueOnce({ data: new Uint8ClampedArray(4) })
      .mockReturnValueOnce({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
  };
  const canvas = { width: 10, height: 10, getContext: vi.fn(() => context) } as unknown as HTMLCanvasElement;
  const failures = await rasterizeSnapshotSvg("<svg/>", canvas, new AbortController().signal);
  expect(failures.map((failure) => failure.stage)).toEqual(["data-url"]);
  expect(context.drawImage).toHaveBeenCalledTimes(2);
});

it("rejects a snapshot when both decoded paths contain no visible pixels", async () => {
  const NativeUrl = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeUrl {
      static createObjectURL = vi.fn(() => "blob:test");
      static revokeObjectURL = vi.fn();
    },
  );
  vi.stubGlobal(
    "Image",
    class {
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(value: string) {
        if (value) queueMicrotask(() => this.onload?.());
      }
    },
  );
  const context = { clearRect: vi.fn(), drawImage: vi.fn(), getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(4) })) };
  const canvas = { width: 10, height: 10, getContext: vi.fn(() => context) } as unknown as HTMLCanvasElement;
  await expect(rasterizeSnapshotSvg("<svg/>", canvas, new AbortController().signal)).rejects.toThrow("Notebook image could not be rendered");
  expect(context.drawImage).toHaveBeenCalledTimes(2);
});

it("reports both decode failures and revokes the lazily-created blob URL", async () => {
  const revoke = vi.fn();
  const NativeUrl = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeUrl {
      static createObjectURL = vi.fn(() => "blob:test");
      static revokeObjectURL = revoke;
    },
  );
  vi.stubGlobal(
    "Image",
    class {
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(value: string) {
        if (value) queueMicrotask(() => this.onerror?.());
      }
    },
  );
  const canvas = { width: 10, height: 10, getContext: vi.fn() } as unknown as HTMLCanvasElement;
  await expect(rasterizeSnapshotSvg("<svg/>", canvas, new AbortController().signal)).rejects.toBeInstanceOf(AggregateError);
  expect(revoke).toHaveBeenCalledWith("blob:test");
});
