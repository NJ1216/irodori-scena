import type { DraftCastSettings } from "../studio/types";

export function draftCastSettingsFor(settings: Record<string, DraftCastSettings>, characterId: string): DraftCastSettings {
  return settings[characterId] ?? { emojiExpressions: false, fillerRichness: false, appearancePriority: "standard" };
}

export function draftCastSettingsRequest(selectedIds: string[], settings: Record<string, DraftCastSettings>) {
  return Object.fromEntries(
    selectedIds.map((characterId) => {
      const value = draftCastSettingsFor(settings, characterId);
      return [characterId, { emoji_expressions: value.emojiExpressions, filler_richness: value.fillerRichness, appearance_priority: value.appearancePriority }];
    }),
  );
}
