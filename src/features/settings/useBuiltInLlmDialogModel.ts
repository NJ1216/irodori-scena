/* eslint-disable react-hooks/set-state-in-effect, react-hooks/refs -- The model preserves the dialog's request-generation guard and controlled selection reset. */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "../../api";
import { chooseDirectory } from "../../api-runtime";
import { isWindows } from "../shared/platform";
import { availableHfTagValues, type HfFilterKind, type HfModel, searchOrderOptions, type HfSearchOrder } from "./huggingFaceModelUi";
import { modelMatches, needsModelMetadata, mergeModelMetadata } from "./hfGgufCatalog";
import { additionError, additionFinished, additionState } from "./modelAddition";
import { useHfGgufSelection } from "./useHfGgufSelection";

export type Download = Awaited<ReturnType<typeof api.huggingFaceDownload>>;
export type LocalModel = Awaited<ReturnType<typeof api.scanExternalLlmModels>>["models"][number];
const wait = () => new Promise((resolve) => window.setTimeout(resolve, 700));

function useHfSearch(blocked: React.RefObject<boolean>) {
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<HfModel[]>([]);
  const [selected, setSelected] = useState("");
  const [maxSizeGb, setMaxSizeGb] = useState<number | null>(null);
  const [order, setOrder] = useState<HfSearchOrder>("downloads");
  const [tags, setTags] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [message, setMessage] = useState("");
  const generation = useRef(0);
  const timer = useRef<number | null>(null);
  const visible = models.filter((model) => modelMatches(model, maxSizeGb ?? 0, tags));
  const tagGroups = useMemo(() => (["publisher", "family", "parameters", "quantization", "purpose", "role", "compatibility"] as const).map((kind) => ({ kind, values: availableHfTagValues(models, tags, kind) })), [models, tags]);
  useEffect(
    () => () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    },
    [],
  );
  async function search(event?: FormEvent, filters = tags, reset = false, requestedOrder = order) {
    event?.preventDefault();
    if (event && blocked.current) return;
    if (timer.current != null) window.clearTimeout(timer.current);
    const nextOrder = searchOrderOptions(requestedOrder, Boolean(event));
    setOrder(nextOrder.selected);
    const current = ++generation.current;
    if (reset) setTags(new Set());
    setSearching(true);
    setCompleted(false);
    setMessage("対応モデルを探しています…");
    try {
      const result = await api.searchHuggingFace(query, [...filters], nextOrder.request);
      if (current !== generation.current) return;
      setModels(result.models);
      setMessage("");
      setCompleted(true);
      setSearching(false);
      const missing = result.models.filter(needsModelMetadata).map(({ repoId, revision }) => ({ repoId, revision }));
      if (missing.length) {
        const metadata = await api.huggingFaceMetadata(missing);
        if (current === generation.current) setModels((value) => mergeModelMetadata(value, metadata.models));
      }
    } catch (error) {
      if (current === generation.current) {
        setCompleted(false);
        setMessage(`検索できませんでした: ${(error as Error).message}`);
      }
    } finally {
      if (current === generation.current) setSearching(false);
    }
  }
  const queue = (next: Set<string>, nextOrder = order) => {
    setTags(next);
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void search(undefined, next, false, nextOrder), 400);
  };
  const toggleTag = (tag: { kind: HfFilterKind; value: string }) => {
    const next = new Set(tags);
    const key = `${tag.kind}:${tag.value}`;
    if (next.has(key)) next.delete(key);
    else next.add(key);
    queue(next);
  };
  return { query, setQuery, models, selected, setSelected, maxSizeGb, setMaxSizeGb, order, setOrder, tags, visible, tagGroups, searching, completed, message, setMessage, search, queue, toggleTag };
}

function useHfDownload(search: ReturnType<typeof useHfSearch>, route: string, onAdded: (name: string) => Promise<void>) {
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState<Download | null>(null);
  const [speed, setSpeed] = useState(0);
  const [token, setToken] = useState("");
  const [hasToken, setHasToken] = useState(false);
  const [needsToken, setNeedsToken] = useState(false);
  const samples = useRef<number[]>([]);
  const previous = useRef<{ bytes: number; at: number } | null>(null);
  const selection = useHfGgufSelection(search.selected, route === "hf", search.maxSizeGb ?? 0, search.tags);
  useEffect(() => {
    if (route === "hf")
      void api
        .huggingFaceTokenStatus()
        .then((value) => setHasToken(value.hasToken))
        .catch(() => setHasToken(false));
  }, [route]);
  useEffect(() => {
    if (search.selected && route === "hf" && !search.visible.some((model) => model.repoId === search.selected)) {
      search.setSelected("");
      setNeedsToken(false);
    }
  }, [route, search]);
  async function download() {
    const model = search.models.find((item) => item.repoId === search.selected);
    if (!model || starting || (isWindows() && !selection.selectedVariant)) return;
    if (model.gated && !hasToken && !token.trim()) {
      setNeedsToken(true);
      return;
    }
    setStarting(true);
    try {
      if (model.gated && token.trim()) {
        await api.saveHuggingFaceToken(token);
        setToken("");
        setHasToken(true);
      }
      const job = await api.downloadHuggingFace(model.repoId, selection.selectedVariant || undefined);
      let next = await api.huggingFaceDownload(job.id);
      setStatus(next);
      setStarting(false);
      previous.current = { bytes: next.downloadedBytes, at: performance.now() };
      while (!additionFinished(next)) {
        await wait();
        next = await api.huggingFaceDownload(job.id);
        const now = performance.now();
        const prior = previous.current;
        if (prior) {
          const sample = Math.max(0, next.downloadedBytes - prior.bytes) / Math.max(0.001, (now - prior.at) / 1000);
          samples.current = [...samples.current.slice(-3), sample];
          setSpeed(samples.current.reduce((sum, value) => sum + value, 0) / samples.current.length);
        }
        previous.current = { bytes: next.downloadedBytes, at: now };
        setStatus(next);
      }
      if (additionState(next) === "complete") await onAdded(model.displayName);
      else search.setMessage(additionError(next));
    } catch (error) {
      search.setMessage((error as Error).message);
    } finally {
      setStarting(false);
      setSpeed(0);
      samples.current = [];
      previous.current = null;
    }
  }
  async function cancel() {
    if (!status) return;
    setStatus({ ...status, state: "cancelling" });
    try {
      setStatus((await api.cancelHuggingFaceDownload(status.id)) as Download);
    } catch (error) {
      search.setMessage(`取消を要求できませんでした: ${(error as Error).message}`);
    }
  }
  return { ...selection, starting, status, speed, token, setToken, needsToken, setNeedsToken, download, cancel };
}

function useLocalModels(onAdded: (name: string) => Promise<void>, setMessage: (value: string) => void) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [selected, setSelected] = useState("");
  const [registering, setRegistering] = useState(false);
  async function choose() {
    try {
      const path = await chooseDirectory("LLMモデルを含むフォルダを選択してください");
      if (!path) return;
      const result = await api.scanExternalLlmModels(path);
      setModels(result.models);
      setMessage(result.models.length ? "利用できるモデルを選んでください。" : "利用できるモデルが見つかりませんでした。");
    } catch (error) {
      setMessage(`フォルダを確認できませんでした: ${(error as Error).message}`);
    }
  }
  async function register() {
    const model = models.find((item) => item.id === selected);
    if (!model) return;
    setRegistering(true);
    try {
      await api.registerExternalLlmModel(model.path);
      await onAdded(model.displayName);
    } catch (error) {
      setMessage(`登録できませんでした: ${(error as Error).message}`);
    } finally {
      setRegistering(false);
    }
  }
  return { models, selected, setSelected, registering, choose, register };
}

export function useBuiltInLlmDialogModel(onAdded: (name: string) => Promise<void>) {
  const [route, setRoute] = useState<"start" | "hf" | "local">("start");
  const blocked = useRef(false);
  const search = useHfSearch(blocked);
  const download = useHfDownload(search, route, onAdded);
  const local = useLocalModels(onAdded, search.setMessage);
  const busy = search.searching || download.starting || local.registering || (!!download.status && !additionFinished(download.status));
  blocked.current = busy;
  return { route, setRoute, search, download, local, busy };
}
