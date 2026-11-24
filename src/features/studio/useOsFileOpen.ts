import { useEffect, useRef } from "react";
import { isDesktopRuntime } from "../../api";
import { classifyDroppedPaths } from "./fileDrop";
import { handleFileRequest } from "./useStudioFileDrop";
import type { StudioController } from "./useStudioController";

export function useOsFileOpen(model: StudioController) {
  const modelRef = useRef(model);
  const requests = useRef<string[][]>([]);
  const processing = useRef(false);
  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  const process = async () => {
    if (processing.current || !modelRef.current.project) return;
    processing.current = true;
    try {
      while (requests.current.length) await handleFileRequest(modelRef.current, classifyDroppedPaths(requests.current.shift()!));
    } finally {
      processing.current = false;
    }
  };

  useEffect(() => {
    if (model.project) void process();
  });

  useEffect(() => {
    if (!isDesktopRuntime) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    let receiving = Promise.resolve();
    const receive = async () => {
      const { invoke } = await import("@tauri-apps/api/core");
      const pending = await invoke<string[][]>("drain_open_file_requests");
      if (!disposed && pending.length) {
        requests.current.push(...pending);
        await process();
      }
    };
    const scheduleReceive = () => {
      receiving = receiving.then(receive).catch(() => undefined);
      return receiving;
    };
    void import("@tauri-apps/api/event")
      .then(async ({ listen }) => {
        unlisten = await listen("scena-open-files", () => void scheduleReceive());
        await scheduleReceive();
        if (disposed) unlisten();
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);
}
