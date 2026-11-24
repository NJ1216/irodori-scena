// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { LlamaCppRuntimeSetting } from "./LlamaCppRuntimeSetting";

it("uses the same compact settings-title action as oMLX management", () => {
  render(<LlamaCppRuntimeSetting compact />);

  expect(screen.getByRole("button", { name: "llama.cpp管理" })).toHaveClass("settings-title-action");
});

it("retains the standalone quiet-button presentation", () => {
  render(<LlamaCppRuntimeSetting />);

  expect(screen.getByRole("button", { name: "llama.cpp管理" })).toHaveClass("quiet-button");
});
