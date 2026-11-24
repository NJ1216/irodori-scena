import { useEffect } from "react";
import { api } from "../../api";
import type { LlmConnection, LlmRegistry } from "../../types";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import type { StudioEffectModel } from "./studioEffectTypes";
import { API_SCHEMA_HASH } from "../../generated/api-schema-hash";

function registryConnection(registry: LlmRegistry): Pick<LlmConnection, "provider" | "baseUrl" | "model" | "apiKeyEnabled" | "hasApiKey"> {
  const card = registry.cards.find((item) => item.id === registry.defaultCardId);
  const endpoint = registry.endpoints.find((item) => item.id === card?.endpointId);
  return { provider: endpoint?.provider ?? "ollama", baseUrl: endpoint?.baseUrl ?? "", model: card?.modelId ?? "", apiKeyEnabled: endpoint?.hasCredential ?? false, hasApiKey: endpoint?.hasCredential ?? false };
}

export function useStudioBootstrap(model: StudioEffectModel) {
  const { editSession, setNotice, setWorkspace, setConnection, setConnectionReady } = model;
  useEffect(() => {
    const initial = editSession.capture();
    // The project is the only read the first screen waits for. Settings and model lists fill in as they
    // arrive, so one slow read (for example while a model loads) never holds the script back.
    const showProject = async () => {
      const [loaded, workspace] = await Promise.all([api.project(), api.workspace()]);
      if (!editSession.isCurrent(initial)) return;
      editSession.replace(loaded);
      setWorkspace(workspace);
      void api.prepareDerivedAudio().catch(() => undefined);
      setNotice("準備できました。キャストを登録して、台本を書き始めましょう。");
    };
    const loadSettings = async () => {
      // connectionReady keeps meaning "every setting read has finished", as before.
      const tts = api.ttsRegistry().then(modelRegistryCache.setTts, () => undefined);
      const catalog = api.ttsCatalog().then(modelRegistryCache.setCatalog, () => undefined);
      const [engine, registry] = await Promise.all([api.engineSettings(), api.llmRegistry()]);
      modelRegistryCache.setLlm(registry);
      setConnection({ ...registryConnection(registry), apiKey: "", ...engine });
      await Promise.all([tts, catalog]);
    };
    const bootstrap = async () => {
      const health = await api.health();
      if (health.apiSchemaHash !== API_SCHEMA_HASH) throw new Error("DEV APIが古いためアプリの再起動が必要です。");
      // A settings failure keeps the project on screen but is reported with the same message as before.
      const settings = loadSettings().then(
        () => null,
        (error: Error) => error,
      );
      await showProject();
      const failure = await settings;
      if (failure) throw failure;
    };
    void bootstrap()
      .catch((error: Error) => setNotice(`起動できません: ${error.message}`))
      .finally(() => setConnectionReady(true));
  }, [editSession, setConnection, setConnectionReady, setNotice, setWorkspace]);
  useEffect(() => {
    const sync = (event: Event) => {
      const registry = (event as CustomEvent<LlmRegistry>).detail;
      setConnection((current) => ({ ...current, ...registryConnection(registry) }));
    };
    window.addEventListener("scena-llm-registry", sync);
    return () => window.removeEventListener("scena-llm-registry", sync);
  }, [setConnection]);
}
