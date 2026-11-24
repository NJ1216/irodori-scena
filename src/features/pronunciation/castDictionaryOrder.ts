import type { Character, PronunciationDictionaryEntry } from "../../types";

const sourceOrder = ["displayName", "familyName", "givenName", "firstPerson", "manual"];
function castEntryOrder(entry: PronunciationDictionaryEntry) {
  const ranks = entry.sourceKeys.map((key) => sourceOrder.indexOf(key)).filter((rank) => rank >= 0);
  return ranks.length ? Math.min(...ranks) : sourceOrder.length;
}

export function castDictionaryGroups(entries: PronunciationDictionaryEntry[], characters: Character[]) {
  const byCharacter = new Map<string, PronunciationDictionaryEntry[]>();
  entries.forEach((entry) => {
    const id = entry.characterId ?? "missing";
    byCharacter.set(id, [...(byCharacter.get(id) ?? []), entry]);
  });
  return characters.flatMap((character) => {
    const rows = byCharacter.get(character.id);
    return rows
      ? [
          {
            character,
            rows: rows
              .map((entry, index) => ({ entry, index }))
              .sort((left, right) => castEntryOrder(left.entry) - castEntryOrder(right.entry) || left.index - right.index)
              .map(({ entry }) => entry),
          },
        ]
      : [];
  });
}
