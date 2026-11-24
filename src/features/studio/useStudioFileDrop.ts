import { useEffect, useRef, useState } from "react";
import { isDesktopRuntime } from "../../api";
import { prepareModalFileDrop } from "../shared/modalFileDrop";
import { classifyDroppedPaths, type FileDropClassification } from "./fileDrop";
import type { StudioController } from "./useStudioController";

async function waitUntilIdle(model: StudioController) {
  for (let index = 0; index < 150 && model.busyRef.current; index += 1) await new Promise((resolve) => window.setTimeout(resolve, 50));
  return !model.busyRef.current;
}

export function useStudioFileDrop(model: StudioController) {
  const [dragged, setDragged] = useState<FileDropClassification | null>(null);
  const modelRef = useRef(model);
  useEffect(() => {
    modelRef.current = model;
  }, [model]);
  useEffect(() => {
    if (!isDesktopRuntime) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/webview")
      .then(async ({ getCurrentWebview }) => {
        unlisten = await getCurrentWebview().onDragDropEvent((event) => {
          if (disposed) return;
          if (event.payload.type === "leave") return setDragged(null);
          if (event.payload.type === "over") return;
          const classified = classifyDroppedPaths("paths" in event.payload ? event.payload.paths : []);
          if (event.payload.type === "enter") return setDragged(classified);
          setDragged(null);
          void handleFileRequest(modelRef.current, classified);
        });
        if (disposed) unlisten();
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);
  return dragged;
}

export async function handleFileRequest(model: StudioController, drop: FileDropClassification) {
  if (drop.kind === "invalid") return model.setNotice(drop.reason);
  if (!prepareModalFileDrop()) return model.setNotice("開いている確認を完了してから、もう一度ファイルを開いてください。");
  if (model.busyRef.current) {
    if (model.autoRenderInProgress.current) await model.stopAutoGeneration();
    else if (model.selectedLineGenerationActive) await model.cancelSelectedLineGeneration();
    else if (model.busyRef.current === "export" && model.exportJob && !model.exportJob.joinOutput) await model.cancelExport();
    else return model.setNotice("処理が完了してから、もう一度ファイルを開いてください。");
    if (!(await waitUntilIdle(model))) return model.setNotice("キャンセル完了後に、もう一度ファイルを開いてください。");
  }
  if (drop.kind === "project") await model.openWorkspace(false, drop.path);
  else await model.prepareCastImport(drop.paths);
  if (drop.unsupported) model.setNotice((current) => `${current} 未対応ファイル${drop.unsupported}件は除外しました。`);
}
