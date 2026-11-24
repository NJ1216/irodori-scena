// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { preventWindowsWebViewShortcutDefault, shortcutLabel } from "./platform";

afterEach(() => vi.unstubAllGlobals());

describe("Windows shortcut mapping", () => {
  it("maps only the macOS modifier names", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    expect(shortcutLabel("⌘R")).toBe("Ctrl+R");
    expect(shortcutLabel("⌘⌥R")).toBe("Ctrl+Alt+R");
    expect(shortcutLabel("⌘⇧R")).toBe("Ctrl+Shift+R");
    expect(shortcutLabel("⌘P")).toBe("Ctrl+P");
    expect(shortcutLabel("⌘⌥P")).toBe("Ctrl+Alt+P");
    expect(shortcutLabel("⌘⇧P")).toBe("Ctrl+Shift+P");
    expect(shortcutLabel("⌘Enter")).toBe("Ctrl+Enter");
    expect(shortcutLabel("⌘O / ⌘S")).toBe("Ctrl+O / Ctrl+S");
    expect(shortcutLabel("⌘F / ⌘A")).toBe("Ctrl+F / Ctrl+A");
    expect(shortcutLabel("⌘Z / ⌘⇧Z")).toBe("Ctrl+Z / Ctrl+Shift+Z");
  });

  it("prevents WebView defaults without stopping app event delivery", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    const event = new KeyboardEvent("keydown", { code: "KeyR", ctrlKey: true, shiftKey: true, cancelable: true });
    preventWindowsWebViewShortcutDefault(event);
    expect(event.defaultPrevented).toBe(true);
    expect(event.cancelBubble).toBe(false);
  });
});
