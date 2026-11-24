// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { captureScriptLineCanvas, captureScriptSceneCanvas } from "./scriptLineCanvasSnapshot";
import { snapshotImageUrl, rasterizeSnapshotSvg } from "../characters/castSnapshotResources";

vi.mock("../characters/castSnapshotResources", () => ({ snapshotImageUrl: vi.fn(async () => "data:image/png;base64,AA=="), rasterizeSnapshotSvg: vi.fn(async () => []) }));
beforeEach(() => vi.clearAllMocks());

it("captures the whole card with its avatar and current editor value", async () => {
  const card = document.createElement("article");
  card.className = "line-card";
  card.innerHTML = '<img src="/avatar.png"><textarea>old</textarea><span>設定</span>';
  card.querySelector("textarea")!.value = "編集中";
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 30, top: 50, width: 400, height: 120 } as DOMRect);
  document.body.append(card);
  try {
    const image = await captureScriptLineCanvas(card, new AbortController().signal);
    const svg = vi.mocked(rasterizeSnapshotSvg).mock.calls.at(-1)?.[0] ?? "";
    expect(svg).toContain("line-card");
    expect(svg).toContain("data:image/png;base64,AA==");
    expect(svg).toContain("編集中");
    expect(snapshotImageUrl).toHaveBeenCalledOnce();
    expect(image).toMatchObject({ width: 400, height: 120, left: 30, top: 50 });
  } finally {
    card.remove();
  }
});

it("captures only the on-screen slice of a tall scene", async () => {
  const scene = document.createElement("article");
  scene.className = "scene-box";
  scene.innerHTML = '<header class="scene-header">シーン</header><div class="line-card"><img src="/offscreen-avatar.png"></div><div class="line-card">発話行</div>';
  vi.spyOn(scene, "getBoundingClientRect").mockReturnValue({ left: 20, top: -800, width: 600, height: 2400 } as DOMRect);
  scene.querySelectorAll<HTMLElement>(".line-card").forEach((line, index) => {
    vi.spyOn(line, "getBoundingClientRect").mockReturnValue({ left: 20, right: 620, top: index ? 100 : -600, bottom: index ? 200 : -500, width: 600, height: 100 } as DOMRect);
  });
  document.body.append(scene);
  try {
    const crop = { left: 20, top: 80, width: 600, height: 600 } as DOMRect;
    const image = await captureScriptSceneCanvas(scene, crop, new AbortController().signal);
    const svg = vi.mocked(rasterizeSnapshotSvg).mock.calls.at(-1)?.[0] ?? "";
    expect(svg).toContain("scene-box");
    expect(svg).toContain("top: -880px");
    expect(svg).not.toContain("offscreen-avatar.png");
    expect(snapshotImageUrl).not.toHaveBeenCalled();
    expect(image).toMatchObject({ left: 20, top: 80, width: 600, height: 600 });
    expect(image.canvas).toMatchObject({ width: 300, height: 300 });
  } finally {
    scene.remove();
  }
});

it("caps every capture at 250000 pixels while preserving display bounds", async () => {
  const scene = document.createElement("article");
  vi.spyOn(scene, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20, width: 1200, height: 900 } as DOMRect);
  document.body.append(scene);
  try {
    const image = await captureScriptSceneCanvas(scene, { left: 10, top: 20, width: 1200, height: 900 } as DOMRect, new AbortController().signal);
    expect(image.canvas.width * image.canvas.height).toBeLessThanOrEqual(250_000);
    expect(image).toMatchObject({ width: 1200, height: 900, left: 10, top: 20 });
    const line = await captureScriptLineCanvas(scene, new AbortController().signal);
    expect(line.canvas.width * line.canvas.height).toBeLessThanOrEqual(250_000);
  } finally {
    scene.remove();
  }
});

it("bounds a 6K visible capture in each dimension and in total pixels", async () => {
  const scene = document.createElement("article");
  vi.spyOn(scene, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 6000, height: 4000 } as DOMRect);
  document.body.append(scene);
  try {
    const image = await captureScriptLineCanvas(scene, new AbortController().signal);
    expect(image).toMatchObject({ width: 6000, height: 4000 });
    expect(image.canvas.width).toBeLessThanOrEqual(3000);
    expect(image.canvas.height).toBeLessThanOrEqual(2000);
    expect(image.canvas.width * image.canvas.height).toBeLessThanOrEqual(250_000);
  } finally {
    scene.remove();
  }
});
