import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";

import { afterEach } from "vitest";

// Use the simulated browser storage, including on Node versions with Web Storage.
const browserWindow = (globalThis as typeof globalThis & { jsdom: { window: Window } }).jsdom.window;
Object.defineProperty(globalThis, "localStorage", { value: browserWindow.localStorage, configurable: true });

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});
