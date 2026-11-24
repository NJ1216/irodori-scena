import type { PronunciationDictionaryEntry } from "../../types";

export function DictionaryScopeCell({ entry, onToggle, busy = false }: { entry: PronunciationDictionaryEntry; onToggle: (scope: "global" | "project", enabled: boolean) => Promise<void>; busy?: boolean }) {
  return (
    <div className="dictionary-scope-tags" aria-label={`${entry.term}の保存先`}>
      {(["global", "project"] as const).map((scope) => {
        const active = (entry.scopes ?? ["global"]).includes(scope);
        return (
          <button key={scope} type="button" className="dictionary-scope-tag" aria-pressed={active} disabled={busy} aria-label={`${scope === "global" ? "SCENA" : "PROJECT"}${busy ? " 保存中" : ""}`} onClick={() => void onToggle(scope, !active)}>
            {scope === "global" ? "SCENA" : "PROJECT"}
          </button>
        );
      })}
    </div>
  );
}
