import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { installMockApi } from "../e2e/mock-api";
// Verification helper for CSS refactors: CSSOM_OUT=<file> pnpm benchmark:ui --grep "dump cssom", run before and after, then compare.
test("dump cssom", async ({ page }) => {
  test.skip(!process.env.CSSOM_OUT, "set CSSOM_OUT to write the dump");
  await installMockApi(page, { lineCount: 6 });
  await page.goto("/");
  await expect(page.locator(".line-card").first()).toBeVisible();
  const rules = await page.evaluate(() => {
    const out: string[] = [];
    const walk = (list: CSSRuleList, depth: string) => {
      for (const r of Array.from(list)) {
        const g = r as CSSGroupingRule;
        if (g.cssRules && !(r instanceof CSSStyleRule)) {
          out.push(depth + r.cssText.split("{")[0].trim() + " {");
          walk(g.cssRules, depth + "  ");
          out.push(depth + "}");
        } else if (r instanceof CSSKeyframesRule) {
          out.push(
            depth +
              "@keyframes " +
              r.name +
              " " +
              Array.from(r.cssRules)
                .map((k) => k.cssText)
                .join(" "),
          );
        } else out.push(depth + r.cssText);
      }
    };
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        walk(sheet.cssRules, "");
      } catch {
        /* cross-origin */
      }
    }
    return out;
  });
  writeFileSync(process.env.CSSOM_OUT!, rules.join("\n"));
});
