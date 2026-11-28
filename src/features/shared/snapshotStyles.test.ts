// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { createCaptureYield, createSnapshotStyler, snapshotStyleProperties } from "./snapshotStyles";

afterEach(() => document.body.replaceChildren());

it("copies what differs and leaves inherited values the parent already passes down", () => {
  const root = document.createElement("div");
  root.style.color = "rgb(10, 20, 30)";
  root.style.display = "flex";
  const same = document.createElement("span");
  const other = document.createElement("span");
  other.style.color = "rgb(200, 0, 0)";
  root.append(same, other);
  document.body.append(root);
  const originals = [root, same, other];
  const copies = originals.map((element) => element.cloneNode(false) as HTMLElement);
  copies.forEach((copy) => copy.removeAttribute("style"));
  const styler = createSnapshotStyler(originals);
  originals.forEach((original, index) => styler(original, copies[index]));
  expect(copies[0].style.color).toBe("rgb(10, 20, 30)");
  expect(copies[0].style.display).toBe("flex");
  expect(copies[1].style.color).toBe("");
  expect(copies[2].style.color).toBe("rgb(200, 0, 0)");
  expect(snapshotStyleProperties.length).toBeLessThan(200);
});

it("yields only after its time budget and stops when the capture is aborted", async () => {
  const pause = createCaptureYield(0);
  const controller = new AbortController();
  await pause(controller.signal);
  controller.abort("cleared");
  await expect(pause(controller.signal)).rejects.toBe("cleared");
});
