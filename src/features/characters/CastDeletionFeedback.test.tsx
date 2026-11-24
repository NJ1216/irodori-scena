import { createRef } from "react";
import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { CastDeletionFeedback } from "./CastDeletionFeedback";
import { renderCastDissolve } from "./renderCastDissolve";

vi.mock("./renderCastDissolve", () => ({ renderCastDissolve: vi.fn(() => () => {}) }));

it("renders particles outside the notebook below the header and removes the layer on cleanup", () => {
  const character = { id: "cast", name: "彩" } as Character;
  const image = { canvas: document.createElement("canvas"), width: 100, height: 100, left: 12, top: 18 };
  const header = document.createElement("div");
  header.className = "app-header";
  header.getBoundingClientRect = () => ({ bottom: 64 }) as DOMRect;
  document.body.append(header);
  const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ left: 30, top: 80 } as DOMRect);
  const { container, unmount } = render(
    <CastDeletionFeedback deletion={{ characters: [character], name: character.name, phase: "dissolving", image }} regionRef={createRef<HTMLDivElement>()}>
      <div className="cast-notebook-spread">
        <div className="cast-notebook-page">彩の記録</div>
      </div>
    </CastDeletionFeedback>,
  );
  const layer = document.body.querySelector(".cast-deletion-particle-layer");
  expect(container.querySelector(".cast-deletion-region")).toHaveClass("has-particles");
  expect(renderCastDissolve).toHaveBeenCalledWith(layer?.querySelector(".cast-deletion-canvas"), expect.objectContaining({ left: 42, top: 98 }), undefined, undefined, expect.objectContaining({ onMetrics: expect.any(Function) }));
  expect(layer).toHaveStyle({ "--cast-particle-header-bottom": "64px" });
  expect(container.querySelector(".cast-deletion-region > div:first-child")).toHaveAttribute("aria-hidden", "true");
  expect(container.querySelector(".cast-deletion-canvas")).toBeNull();
  unmount();
  expect(document.body.querySelector(".cast-deletion-particle-layer")).toBeNull();
  bounds.mockRestore();
  header.remove();
});

it("keeps the live notebook visible for the CSS fallback when capture is transparent", () => {
  const regionRef = createRef<HTMLDivElement>();
  const { container } = render(
    <CastDeletionFeedback deletion={{ characters: [], name: "彩", phase: "dissolving", image: null }} regionRef={regionRef}>
      <div className="cast-notebook-spread">
        <div className="cast-notebook-page">彩の記録</div>
      </div>
    </CastDeletionFeedback>,
  );
  expect(container.querySelector(".cast-deletion-region")).toHaveClass("is-css-fallback");
  expect(container.querySelector(".cast-notebook-page")).toHaveTextContent("彩の記録");
  expect(document.body.querySelector(".cast-deletion-particle-layer")).toBeNull();
  expect(container.querySelector('[role="status"]')).toHaveTextContent("「彩」を削除しました");
});
