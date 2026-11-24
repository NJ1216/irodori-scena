import { describe, expect, it } from "vitest";
import type { Character, PronunciationDictionaryEntry } from "../../types";
import { castDictionaryGroups } from "./castDictionaryOrder";

const entry = (id: string, characterId: string, term: string, sourceKeys: string[]): PronunciationDictionaryEntry => ({ id, characterId, term, reading: "", source: "cast", sourceKeys, suggestedReading: "", userEdited: false, locked: false });

describe("cast dictionary ordering", () => {
  it("follows cast-page order and display-name, family-name, given-name, first-person order", () => {
    const characters = [
      { id: "b", name: "B" },
      { id: "a", name: "A" },
    ] as Character[];
    const entries = [entry("a-first", "a", "僕", ["firstPerson"]), entry("b-given", "b", "太郎", ["givenName"]), entry("b-display", "b", "タロ", ["displayName"]), entry("b-family", "b", "山田", ["familyName"])];
    const groups = castDictionaryGroups(entries, characters);
    expect(groups.map((group) => group.character.id)).toEqual(["b", "a"]);
    expect(groups[0].rows.map((row) => row.id)).toEqual(["b-display", "b-family", "b-given"]);
  });
});
