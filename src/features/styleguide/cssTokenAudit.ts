export type CssTokenAuditItem = {
  category: "色" | "余白" | "角丸" | "固定寸法";
  selector: string;
  property: string;
  value: string;
  line: number;
  source: string;
};

const colorLiteral = /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?)\(/i;
const lengthLiteral = /(?:^|\s)[1-9]\d*(?:\.\d+)?(?:px|rem|em)\b/;

function lineAt(source: string, index: number) {
  return source.slice(0, index).split("\n").length;
}

function selectorAt(source: string, index: number) {
  const ruleStart = source.lastIndexOf("{", index);
  const previousRuleEnd = source.lastIndexOf("}", ruleStart);
  return source.slice(previousRuleEnd + 1, ruleStart).trim() || ":root";
}

export function findUntokenizedCssValues(source: string, sourceName: string): CssTokenAuditItem[] {
  const declarations = /([\w-]+)\s*:\s*([^;{}]+);/g;
  const results: CssTokenAuditItem[] = [];
  for (const match of source.matchAll(declarations)) {
    const [raw, property, value] = match;
    const index = match.index ?? 0;
    if (value.includes("var(--")) continue;
    const shared = {
      selector: selectorAt(source, index),
      property,
      value: value.trim(),
      line: lineAt(source, index),
      source: sourceName,
    };
    if (colorLiteral.test(value)) results.push({ category: "色", ...shared });
    if (lengthLiteral.test(value)) {
      const category = /^(?:margin|padding|gap|row-gap|column-gap)$/.test(property) ? "余白" : property === "border-radius" ? "角丸" : "固定寸法";
      results.push({ category, ...shared });
    }
    void raw;
  }
  return results;
}

export function summarizeCssTokenAudit(items: CssTokenAuditItem[]) {
  return items.reduce<Record<CssTokenAuditItem["category"], number>>((summary, item) => ({ ...summary, [item.category]: summary[item.category] + 1 }), { 色: 0, 余白: 0, 角丸: 0, 固定寸法: 0 });
}
