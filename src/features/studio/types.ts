import type { LlmConnection } from "../../types";

export type Tab = "script" | "characters" | "pronunciation" | "draft" | "settings" | "lora";
export type LlmProvider = "ollama" | "lmstudio" | "openai" | "scena-local";
export type DraftCastSettings = {
  emojiExpressions: boolean;
  fillerRichness: boolean;
  appearancePriority: "main" | "supporting" | "standard";
};
export type DraftPerformanceSettings = {
  speechRateMin: number;
  speechRateMax: number;
  gapMin: number;
  gapMax: number;
  allowedEmojis: string[];
};
export type DraftComposerState = {
  selectedIds: string[];
  minutes: number;
  theme: string;
  apiKey: string;
  provider: LlmProvider;
  baseUrl: string;
  model: string;
  castSettings: Record<string, DraftCastSettings>;
  performance: DraftPerformanceSettings;
  simultaneousCues: boolean;
  overlappingSpeech: boolean;
};
export type LineAssistantTarget = { kind: "insert"; sceneId: string; beforeLineId?: string } | { kind: "rewrite"; lineIds: string[] };
export type AutoScrollTarget = "playback" | "export";
export type FocusedTextInput = {
  sceneId: string;
  lineId: string;
  element: import("../script/EmojiTextArea").LineTextEditorElement;
};

export const llmPresets: Record<LlmProvider, { label: string; baseUrl: string }> = {
  ollama: { label: "Ollama（ローカル）", baseUrl: "http://127.0.0.1:11434/v1" },
  lmstudio: {
    label: "LM Studio（ローカル）",
    baseUrl: "http://127.0.0.1:1234/v1",
  },
  openai: { label: "外部LLM（OpenAI互換）", baseUrl: "" },
  "scena-local": { label: "SCENA内蔵LLM", baseUrl: "http://scena.local/v1" },
};

export const defaultLlmConnection: LlmConnection = {
  provider: "ollama",
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "",
  apiKeyEnabled: false,
  hasApiKey: false,
  apiKey: "",
  engineDir: "",
  engineDirVerified: false,
};
