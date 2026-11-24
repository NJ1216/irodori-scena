import { describe, expect, it } from "vitest";
import { isApiRequest, isMarkedTauriEntry, scenaViteConfig, viteWatchIgnores } from "../../vite.config";

describe("Tauri development Vite guard", () => {
  it("removes the fixed-port API proxy only in Tauri mode", () => {
    expect(scenaViteConfig("tauri").server?.proxy).toBeUndefined();
    expect(scenaViteConfig("development").server?.proxy).toMatchObject({
      "/api": "http://127.0.0.1:8787",
    });
  });

  it("requires the Tauri marker on the development document entry", () => {
    expect(isMarkedTauriEntry("/?scena-tauri=1")).toBe(true);
    expect(isMarkedTauriEntry("/index.html?scena-tauri=1")).toBe(true);
    expect(isMarkedTauriEntry("/")).toBe(false);
    expect(isMarkedTauriEntry("/?scena-tauri=0")).toBe(false);
  });

  it("does not watch managed runtimes or generated application data", () => {
    expect(viteWatchIgnores).toEqual(expect.arrayContaining(["**/.venv/**", "**/scena-data/**", "**/src-tauri/target/**", "**/src-tauri/binaries/**", "**/src-tauri/resources/environment-manager/**", "**/native/scena-native/target/**"]));
    expect(scenaViteConfig("tauri").server?.watch?.ignored).toBe(viteWatchIgnores);
  });

  it.each(["/api/project", "/api/project?refresh=1", "/media/take.wav", "/global-media/character.png"])("recognizes API-backed path %s", (path) => {
    expect(isApiRequest(path)).toBe(true);
  });

  it.each(["/", "/settings", "/apiary", "/media-library"])("leaves frontend path %s alone", (path) => {
    expect(isApiRequest(path)).toBe(false);
  });
});
