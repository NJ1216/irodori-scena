// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { cancelScriptLineRestoration, finishScriptLineRestoration, prepareScriptLineRestoration } from "./scriptLineRestorationMotion";

const project = (ids: string[]) => ({ id: "project", scenes: [{ lines: ids.map((id) => ({ id })) }] }) as StudioProject;
const rectangle = (top: number) => ({ left: 10, top, right: 610, bottom: top + 100 }) as DOMRect;

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  document.body.innerHTML = '<section class="script-canvas"><article class="line-card" data-line-id="one"></article><article class="line-card" data-line-id="three"></article></section>';
  vi.spyOn(document.querySelector<HTMLElement>(".script-canvas")!, "getBoundingClientRect").mockReturnValue(rectangle(0));
  for (const card of document.querySelectorAll<HTMLElement>(".line-card")) {
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue(rectangle(card.dataset.lineId === "one" ? 0 : 110));
    card.animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
    card.scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cancelScriptLineRestoration();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("expands only lines restored by Undo and moves surviving cards", () => {
  expect(prepareScriptLineRestoration(project(["one", "three"]), project(["one", "two", "three"]))).toEqual(["two"]);
  const restored = document.createElement("article");
  restored.className = "line-card";
  restored.dataset.lineId = "two";
  restored.animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
  restored.scrollIntoView = vi.fn();
  vi.spyOn(restored, "getBoundingClientRect").mockReturnValue(rectangle(110));
  document.querySelector('[data-line-id="three"]')!.before(restored);
  vi.spyOn(document.querySelector<HTMLElement>('[data-line-id="three"]')!, "getBoundingClientRect").mockReturnValue(rectangle(220));

  expect(finishScriptLineRestoration(project(["one", "two", "three"]))).toBeNull();
  expect(restored.animate).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ clipPath: "inset(49% 0 49%)" })]), expect.objectContaining({ duration: 260 }));
  expect(document.querySelector<HTMLElement>('[data-line-id="three"]')!.animate).toHaveBeenCalledOnce();
  expect(document.querySelector<HTMLElement>('[data-line-id="one"]')!.animate).not.toHaveBeenCalled();
});

it("does not animate unrelated project updates", () => {
  expect(prepareScriptLineRestoration(project(["one", "three"]), project(["one", "three"]))).toEqual([]);
  expect(finishScriptLineRestoration(project(["one", "three"]))).toBeNull();
  expect(document.querySelector<HTMLElement>('[data-line-id="one"]')!.animate).not.toHaveBeenCalled();
});

it("ignores lines belonging to a restored scene", () => {
  const before = { id: "project", scenes: [{ id: "existing", lines: [{ id: "one" }] }] } as StudioProject;
  const after = { id: "project", scenes: [...before.scenes, { id: "restored-scene", lines: [{ id: "two" }] }] } as StudioProject;
  expect(prepareScriptLineRestoration(before, after)).toEqual([]);
});

it("expands multiple restored lines in one update and scrolls to the first offscreen line", () => {
  expect(prepareScriptLineRestoration(project(["one", "three"]), project(["one", "two", "four", "three"]))).toEqual(["two", "four"]);
  for (const id of ["two", "four"]) {
    const card = document.createElement("article");
    card.className = "line-card";
    card.dataset.lineId = id;
    card.animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
    card.scrollIntoView = vi.fn();
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue(rectangle(300));
    document.querySelector('[data-line-id="three"]')!.before(card);
  }
  expect(finishScriptLineRestoration(project(["one", "two", "four", "three"]))).toBeNull();
  expect(document.querySelector<HTMLElement>('[data-line-id="two"]')!.animate).toHaveBeenCalledOnce();
  expect(document.querySelector<HTMLElement>('[data-line-id="four"]')!.animate).toHaveBeenCalledOnce();
  expect(document.querySelector<HTMLElement>('[data-line-id="two"]')!.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
});

it("waits for a virtual row and skips motion when reduced motion is requested", () => {
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList);
  prepareScriptLineRestoration(project(["one"]), project(["one", "two"]));
  expect(finishScriptLineRestoration(project(["one", "two"]))).toBe("two");
  const restored = document.createElement("article");
  restored.className = "line-card";
  restored.dataset.lineId = "two";
  restored.animate = vi.fn();
  restored.scrollIntoView = vi.fn();
  document.querySelector(".script-canvas")!.append(restored);
  expect(finishScriptLineRestoration(project(["one", "two"]))).toBeNull();
  expect(restored.animate).not.toHaveBeenCalled();
  expect(restored.scrollIntoView).not.toHaveBeenCalled();
});

it("cancels a pending restoration when the view changes", () => {
  prepareScriptLineRestoration(project(["one"]), project(["one", "two"]));
  expect(finishScriptLineRestoration(project(["one", "two"]))).toBe("two");
  cancelScriptLineRestoration();
  expect(finishScriptLineRestoration(project(["one", "two"]))).toBeNull();
});
