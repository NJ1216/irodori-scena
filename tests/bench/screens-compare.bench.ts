import { test } from "@playwright/test";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";

// Compares two SHOT_DIR-style folders (OLD_DIR, NEW_DIR) and writes red diff images into DIFF_DIR.
test("screens-compare", async ({ page }) => {
  test.skip(!process.env.OLD_DIR, "set OLD_DIR, NEW_DIR and DIFF_DIR");
  await page.goto("about:blank");
  const out: string[] = [];
  for (const name of readdirSync(process.env.OLD_DIR!).filter((n) => n.endsWith(".png"))) {
    const a = readFileSync(process.env.OLD_DIR + "/" + name).toString("base64");
    const b = readFileSync(process.env.NEW_DIR + "/" + name).toString("base64");
    const r = await page.evaluate(
      async ([a, b]) => {
        const load = (s: string) =>
          new Promise<HTMLImageElement>((res) => {
            const i = new Image();
            i.onload = () => res(i);
            i.src = "data:image/png;base64," + s;
          });
        const [ia, ib] = await Promise.all([load(a), load(b)]);
        const px = (i: HTMLImageElement) => {
          const c = document.createElement("canvas");
          c.width = i.width;
          c.height = i.height;
          const x = c.getContext("2d")!;
          x.drawImage(i, 0, 0);
          return x.getImageData(0, 0, i.width, i.height);
        };
        const da = px(ia),
          db = px(ib);
        const out = new ImageData(ia.width, ia.height);
        let changed = 0,
          max = 0;
        for (let k = 0; k < da.data.length; k += 4) {
          const d = Math.max(Math.abs(da.data[k] - db.data[k]), Math.abs(da.data[k + 1] - db.data[k + 1]), Math.abs(da.data[k + 2] - db.data[k + 2]));
          max = Math.max(max, d);
          if (d > 0) changed++;
          const g = Math.round(da.data[k] * 0.3 + 160);
          out.data[k] = d > 0 ? 255 : g;
          out.data[k + 1] = d > 0 ? 0 : g;
          out.data[k + 2] = d > 0 ? 0 : g;
          out.data[k + 3] = 255;
        }
        const c = document.createElement("canvas");
        c.width = ia.width;
        c.height = ia.height;
        c.getContext("2d")!.putImageData(out, 0, 0);
        return { changed, max, pct: ((changed / (da.data.length / 4)) * 100).toFixed(2), png: c.toDataURL("image/png").split(",")[1] };
      },
      [a, b],
    );
    writeFileSync(process.env.DIFF_DIR + "/" + name, Buffer.from(r.png, "base64"));
    out.push(name + " changed=" + r.changed + " (" + r.pct + "%) maxChannelDelta=" + r.max);
  }
  console.log("CMP\n" + out.join("\n"));
});
