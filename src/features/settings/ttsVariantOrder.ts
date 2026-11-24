import type { TtsCatalogVariant } from "../../types";

export function orderTtsVariantsForDisplay(variants: TtsCatalogVariant[]) {
  return [...variants].sort((a, b) => {
    if (a.id === "pytorch-fp32" || b.id === "pytorch-fp32") return a.id === "pytorch-fp32" ? -1 : 1;
    return a.recommendedOrder - b.recommendedOrder;
  });
}
