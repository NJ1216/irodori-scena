/* eslint-disable react-hooks/set-state-in-effect -- Reset requests and selections at repository and filter boundaries. */
import { useEffect, useState } from "react";
import { api } from "../../api";
import type { HfGgufVariant } from "../../api-llm";
import { variantMatches } from "./hfGgufCatalog";
import { isWindows } from "../shared/platform";

type Catalog = { repoId: string; variants: HfGgufVariant[]; message: string };
type Selection = { repoId: string; id: string };

export function useHfGgufSelection(selectedRepo: string, active: boolean, maxGb: number, tags: Set<string>) {
  const repoId = active && isWindows() ? selectedRepo : "";
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  useEffect(() => {
    setCatalog(null);
    setSelection(null);
    if (!repoId) return;
    let current = true;
    setCatalog({ repoId, variants: [], message: "量子化を確認しています…" });
    void api
      .huggingFaceGgufVariants(repoId)
      .then((value) => {
        if (!current) return;
        setCatalog({ repoId, variants: value.variants, message: value.variants.length ? "" : "取得できる量子化が見つかりませんでした。" });
        if (value.variants.length === 1) setSelection({ repoId, id: value.variants[0].id });
      })
      .catch((error) => {
        if (current) setCatalog({ repoId, variants: [], message: `量子化を確認できませんでした: ${(error as Error).message}` });
      });
    return () => {
      current = false;
    };
  }, [repoId]);
  const owned = catalog?.repoId === repoId ? catalog : null;
  const variants = (owned?.variants ?? []).filter((variant) => variantMatches(variant, maxGb, tags));
  const selectedVariant = selection?.repoId === repoId && variants.some((variant) => variant.id === selection.id) ? selection.id : "";
  useEffect(() => {
    if (selection && !selectedVariant) setSelection(null);
  }, [selection, selectedVariant]);
  const selectVariant = (id: string) => setSelection({ repoId, id });
  const message = owned?.message || (owned?.variants.length && !variants.length ? "検索条件に合う量子化がありません。" : "");
  return { variants, selectedVariant, selectVariant, message };
}
