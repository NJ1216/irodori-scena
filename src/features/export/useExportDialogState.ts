import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { defaultExportDirectory } from "../../api-runtime";
import type { ExportJob, RhubarbStatus, StudioProject } from "../../types";
import { type Format, loadSettings, previewNames, type Settings, STORAGE_KEY } from "./exportSettings";

type Start = (settings: Settings & { destinationDir: string }) => Promise<unknown>;

function useDefaultDestination(setDestinationDir: (path: string) => void) {
  useEffect(() => {
    let active = true;
    void defaultExportDirectory()
      .then((path) => {
        if (active && path) setDestinationDir(path);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [setDestinationDir]);
}

export function useExportDialogState(project: StudioProject, job: ExportJob | null, onStart: Start) {
  const [settings, setSettings] = useState(loadSettings);
  const [destinationDir, setDestinationDir] = useState("");
  const [error, setError] = useState("");
  const [rhubarbPrompt, setRhubarbPrompt] = useState<RhubarbStatus | null>(null);
  useDefaultDestination(setDestinationDir);
  const running = Boolean(job && ["preparing", "generating", "aligning", "writing"].includes(job.status));
  const done = Boolean(job && ["completed", "completed_with_warnings"].includes(job.status));
  const previews = useMemo(() => previewNames(project, settings), [project, settings]);
  const duplicate = settings.layout === "split" && new Set(previews.map((item) => item.normalize("NFC").toLocaleLowerCase())).size !== previews.length;
  const invalid = !settings.formats.length || (settings.layout === "split" && settings.naming.every((item) => item === "none")) || duplicate || !destinationDir;
  const update = (patch: Partial<Settings>) => setSettings((current) => ({ ...current, ...patch }));
  async function submit() {
    setError("");
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    try {
      await onStart({ ...settings, destinationDir });
    } catch (reason) {
      setError((reason as Error).message);
    }
  }
  async function start() {
    if (settings.formats.includes("lab")) {
      try {
        const status = await api.rhubarbStatus();
        if (!status.ready || status.updateAvailable) {
          setRhubarbPrompt(status);
          return;
        }
      } catch (reason) {
        setError((reason as Error).message);
        return;
      }
    }
    await submit();
  }
  function toggleFormat(value: Format, checked: boolean) {
    if (value === "lab" && checked) {
      update({ formats: Array.from(new Set([...settings.formats, "wav", "lab"])), layout: "split" });
      return;
    }
    if (value === "wav" && !checked && settings.formats.includes("lab")) return;
    update({ formats: checked ? [...settings.formats, value] : settings.formats.filter((item) => item !== value) });
  }
  function selectLayout(layout: Settings["layout"]) {
    update({
      layout,
      formats: layout === "joined" ? settings.formats.filter((format) => format !== "lab") : settings.formats,
    });
  }
  return { settings, destinationDir, setDestinationDir, error, rhubarbPrompt, setRhubarbPrompt, running, done, previews, duplicate, invalid, update, submit, start, toggleFormat, selectLayout };
}
