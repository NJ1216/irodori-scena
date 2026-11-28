// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useInlineValidation } from "./useInlineValidation";

it("keeps a field message until that field is edited, and a form message until the form changes", () => {
  const { result } = renderHook(() => useInlineValidation());
  act(() => result.current.report("キャスト名は必須です。", "castName"));
  expect(result.current.fieldError("castName")).toBe("キャスト名は必須です。");
  expect(result.current.formError).toBe("");

  act(() => result.current.clear("profile"));
  act(() => result.current.clearForm());
  expect(result.current.fieldError("castName")).toBe("キャスト名は必須です。");
  act(() => result.current.clear("castName"));
  expect(result.current.fieldError("castName")).toBe("");

  act(() => result.current.report("先に基準ボイスを選んでください。"));
  expect(result.current.formError).toBe("先に基準ボイスを選んでください。");
  act(() => result.current.clear("castName"));
  expect(result.current.formError).toBe("先に基準ボイスを選んでください。");
  act(() => result.current.clearForm());
  expect(result.current.formError).toBe("");
});

it("focuses the field at fault", async () => {
  const input = document.createElement("input");
  input.dataset.validationField = "castName";
  document.body.append(input);
  const { result } = renderHook(() => useInlineValidation());
  act(() => result.current.report("キャスト名は必須です。", "castName"));
  await new Promise((resolve) => requestAnimationFrame(resolve));
  expect(document.activeElement).toBe(input);
  input.remove();
});
