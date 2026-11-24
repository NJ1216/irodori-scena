import { describe, expect, it } from "vitest";
import { closeStyleGuide, isStyleGuideLocation, openStyleGuide } from "./styleGuideNavigation";

describe("isStyleGuideLocation", () => {
  it("accepts the legacy browser path", () => {
    expect(isStyleGuideLocation({ pathname: "/style-guide", search: "" })).toBe(true);
  });

  it("accepts the query route used inside Tauri", () => {
    expect(isStyleGuideLocation({ pathname: "/index.html", search: "?style-guide=" })).toBe(true);
  });

  it("does not expose the guide on an ordinary app URL", () => {
    expect(isStyleGuideLocation({ pathname: "/index.html", search: "" })).toBe(false);
  });

  it("opens and closes without leaving the current document path", () => {
    window.history.replaceState(null, "", "/index.html?project=demo");
    openStyleGuide();
    expect(window.location.pathname).toBe("/index.html");
    expect(window.location.search).toContain("style-guide=");
    closeStyleGuide();
    expect(window.location.href).toContain("/index.html?project=demo");
    expect(window.location.search).not.toContain("style-guide");
  });
});
