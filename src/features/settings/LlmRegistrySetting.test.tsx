// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { LlmRegistry } from "../../types";
import { LlmRegistrySetting } from "./LlmRegistrySetting";
import { modelRegistryCache } from "../shared/modelRegistryCache";

vi.mock("./OmlxRuntimeSetting", () => ({ OmlxRuntimeSetting: () => null }));
vi.mock("./LlamaCppRuntimeSetting", () => ({ LlamaCppRuntimeSetting: () => null }));
const registry = {
  version: 3,
  defaultCardId: null,
  endpoints: [{ id: "ollama", provider: "ollama", displayName: "Ollama", baseUrl: "http://127.0.0.1:11434/v1", hasCredential: false }],
  cards: [{ id: "gemma", endpointId: "ollama", modelId: "gemma4:12b-mlx", displayName: "Gemma", source: "remote", settings: {} }],
} as LlmRegistry;

beforeEach(() => modelRegistryCache.reset());
afterEach(() => vi.restoreAllMocks());

it("renders a startup-cached registry before the refresh request completes", () => {
  modelRegistryCache.setLlm({ ...registry, defaultCardId: "gemma" });
  vi.spyOn(api, "llmRegistry").mockReturnValue(new Promise(() => undefined));

  render(<LlmRegistrySetting />);

  expect(screen.getByRole("button", { name: /Gemma/ })).toBeInTheDocument();
});

it("reflects the newly added default model without a separate selection request", async () => {
  vi.spyOn(api, "llmRegistry").mockResolvedValue({ ...registry, defaultCardId: "gemma" });
  const card = { ...registry.cards[0], id: "new-card", modelId: "new-model", displayName: "New model" };
  const saved = { ...registry, defaultCardId: card.id, cards: [...registry.cards, card] };
  vi.spyOn(api, "inspectRemoteLlmModels").mockResolvedValue({ models: [card.modelId] });
  const add = vi.spyOn(api, "createRemoteLlmSetting").mockResolvedValue({ registry: saved, card });
  const select = vi.spyOn(api, "setDefaultLlmCard");
  const changed = vi.fn();
  window.addEventListener("scena-llm-registry", changed);
  try {
    render(<LlmRegistrySetting />);
    fireEvent.click(await screen.findByRole("button", { name: /Gemma/ }));
    fireEvent.click(await screen.findByRole("button", { name: /接続先を追加/ }));
    const dialog = within(await screen.findByRole("dialog", { name: "接続先からLLMを追加" }));
    fireEvent.click(dialog.getByRole("button", { name: "モデルを確認" }));
    await waitFor(() => expect(dialog.getByRole("button", { name: "このモデルを追加" })).toBeEnabled());
    fireEvent.click(dialog.getByRole("button", { name: "このモデルを追加" }));
    expect(await screen.findByRole("button", { name: /New model/ })).toBeInTheDocument();
    expect(add).toHaveBeenCalledWith(expect.objectContaining({ provider: "ollama", modelId: "new-model" }));
    expect(select).not.toHaveBeenCalled();
    expect((changed.mock.lastCall?.[0] as CustomEvent).detail.defaultCardId).toBe(card.id);
  } finally {
    window.removeEventListener("scena-llm-registry", changed);
  }
});

it("adds Anthropic as the official endpoint with a required key and labels its card", async () => {
  vi.spyOn(api, "llmRegistry").mockResolvedValue({ ...registry, defaultCardId: "gemma" });
  const endpoint = { id: "claude", provider: "openai", displayName: "openai", baseUrl: "https://api.anthropic.com/v1", hasCredential: true } as LlmRegistry["endpoints"][number];
  const card = { ...registry.cards[0], id: "claude-card", endpointId: "claude", modelId: "claude-sonnet-5-5", displayName: "Claude" };
  const saved = { ...registry, defaultCardId: card.id, endpoints: [...registry.endpoints, endpoint], cards: [...registry.cards, card] };
  const inspect = vi.spyOn(api, "inspectRemoteLlmModels").mockResolvedValue({ models: [card.modelId] });
  const add = vi.spyOn(api, "createRemoteLlmSetting").mockResolvedValue({ registry: saved, card });
  render(<LlmRegistrySetting />);
  fireEvent.click(await screen.findByRole("button", { name: /Gemma/ }));
  fireEvent.click(await screen.findByRole("button", { name: /接続先を追加/ }));
  const dialog = within(await screen.findByRole("dialog", { name: "接続先からLLMを追加" }));
  fireEvent.change(dialog.getByRole("combobox", { name: "種類" }), { target: { value: "anthropic" } });
  expect(dialog.getByRole("textbox", { name: "URL" })).toHaveValue("https://api.anthropic.com/v1");
  expect(dialog.queryByRole("checkbox", { name: /API Keyを設定/ })).not.toBeInTheDocument();
  expect(dialog.getByRole("button", { name: "モデルを確認" })).toBeDisabled();
  fireEvent.change(dialog.getByLabelText(/^API Key(?!を)/), { target: { value: "sk-ant-test" } });
  fireEvent.click(dialog.getByRole("button", { name: "モデルを確認" }));
  await waitFor(() => expect(dialog.getByRole("button", { name: "このモデルを追加" })).toBeEnabled());
  fireEvent.click(dialog.getByRole("button", { name: "このモデルを追加" }));
  const expected = { provider: "openai", baseUrl: "https://api.anthropic.com/v1", credential: "sk-ant-test" };
  expect(inspect).toHaveBeenCalledWith(expected);
  expect(add).toHaveBeenCalledWith({ ...expected, modelId: "claude-sonnet-5-5" });
  const added = await screen.findByRole("button", { name: /Claude/ });
  expect(within(added).getByText("Anthropic")).toBeInTheDocument();
});

it("does not present an unselected Ollama card as the default", async () => {
  vi.spyOn(api, "llmRegistry").mockResolvedValue(registry);
  render(<LlmRegistrySetting />);
  expect(await screen.findByRole("button", { name: /LLMモデルを選択してください/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "LLMモデルの詳細" })).not.toBeInTheDocument();
});

it("persists an Ollama selection and notifies the AI feature only with the saved registry", async () => {
  vi.spyOn(api, "llmRegistry").mockResolvedValue(registry);
  const saved = { ...registry, defaultCardId: "gemma" };
  const select = vi.spyOn(api, "setDefaultLlmCard").mockResolvedValue(saved);
  const changed = vi.fn();
  window.addEventListener("scena-llm-registry", changed);
  try {
    render(<LlmRegistrySetting />);
    const trigger = await screen.findByRole("button", { name: /LLMモデルを選択してください/ });
    changed.mockClear();
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("option", { name: /Gemma/ }));
    await waitFor(() => expect(select).toHaveBeenCalledWith("gemma"));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect((changed.mock.calls[0][0] as CustomEvent).detail).toEqual(saved);
    expect(screen.getByRole("button", { name: /Gemma/ })).toHaveTextContent("Ollama");
  } finally {
    window.removeEventListener("scena-llm-registry", changed);
  }
});

it("offers llama.cpp models and external connections on Windows", async () => {
  vi.stubGlobal("navigator", { platform: "Win32" });
  const local = { ...registry.cards[0], id: "local", source: "managed" as const, displayName: "Local model" };
  const value = { ...registry, defaultCardId: "local", cards: [...registry.cards, local] };
  vi.spyOn(api, "llmRegistry").mockResolvedValue(value);
  const select = vi.spyOn(api, "setDefaultLlmCard");
  try {
    render(<LlmRegistrySetting />);
    fireEvent.click(await screen.findByRole("button", { name: /Local model/ }));
    expect(await screen.findByRole("option", { name: /Gemma/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Local model/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /SCENA内蔵LLMにモデルを追加/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /接続先を追加/ })).toBeInTheDocument();
    expect(select).not.toHaveBeenCalled();
    expect(value.cards).toHaveLength(2);
  } finally {
    vi.unstubAllGlobals();
  }
});
