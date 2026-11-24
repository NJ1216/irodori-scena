import { describe, expect, it } from "vitest";
import type { TtsCatalogItem } from "../../types";
import { recommendedTtsModel } from "./useTtsInstallJob";

const item = (id: string, recommendedOrder: number, legacy = false, installable = true) => ({ id, displayName: id, repo: id, installable, legacy, recommendedOrder }) as TtsCatalogItem;

describe("recommendedTtsModel", () => {
  it("selects the lowest recommendation order after excluding legacy and unavailable models", () => {
    expect(recommendedTtsModel([item("legacy", 0, true), item("unavailable", 1, false, false), item("second", 3), item("first", 2)])?.id).toBe("first");
  });

  it("returns null when there is no eligible model", () => {
    expect(recommendedTtsModel([item("legacy", 1, true), item("unavailable", 2, false, false)])).toBeNull();
  });
});
