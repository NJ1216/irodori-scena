import { expect, it } from "vitest";
import { formatDecimalBytes, formatGb } from "./formatBytes";

it("formats gigabytes as decimal units (1 GB = 1,000,000,000 bytes)", () => {
  expect(formatGb(1_000_000_000)).toBe("1.0 GB");
  expect(formatGb(2 * 1024 ** 3)).toBe("2.1 GB");
  expect(formatGb(1_234_000_000, 2)).toBe("1.23 GB");
});

it("switches between MB and GB at one decimal gigabyte", () => {
  expect(formatDecimalBytes(999_400_000)).toBe("999 MB");
  expect(formatDecimalBytes(999_500_000)).toBe("1.0 GB");
  expect(formatDecimalBytes(999_999_999)).toBe("1.0 GB");
  expect(formatDecimalBytes(1)).toBe("1 MB");
  expect(formatDecimalBytes(1_500_000_000)).toBe("1.5 GB");
});
