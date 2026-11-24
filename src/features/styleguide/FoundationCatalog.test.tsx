import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FoundationCatalog } from "./FoundationCatalog";

describe("FoundationCatalog", () => {
  it("catalogs every footer resource meter icon", () => {
    render(<FoundationCatalog />);

    expect(screen.getByRole("img", { name: "メモリ" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "GPUメモリ" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "GPU使用率" })).toBeInTheDocument();
  });
});
