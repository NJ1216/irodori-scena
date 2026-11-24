import { useState } from "react";
import type { DraftComposerState } from "./types";
import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";

const initialDraftComposer: DraftComposerState = {
  selectedIds: [],
  minutes: 3,
  theme: "",
  apiKey: "",
  provider: "ollama",
  baseUrl: "",
  model: "",
  castSettings: {},
  simultaneousCues: true,
  overlappingSpeech: true,
  performance: {
    speechRateMin: 0.85,
    speechRateMax: 1.35,
    gapMin: -2,
    gapMax: 5,
    allowedEmojis: IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji),
  },
};

export function useDraftComposerState() {
  return useState<DraftComposerState>(initialDraftComposer);
}
