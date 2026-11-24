import { useRef, useState } from "react";
import { api, chooseCastFiles } from "../../api";
import type { CastImportPreparation } from "../../types";
import { castImportResultMessage, commitUncontestedCastImport, skippedCastImportReasons } from "../characters/castImportWorkflow";
import type { StudioState } from "./useStudioState";

export function useCastImport(model: Pick<StudioState, "editSession" | "setNotice" | "setTab">) {
  const importOperation = useRef(model.editSession.capture());
  const [castImportPreparation, setCastImportPreparation] = useState<CastImportPreparation | null>(null);
  const [skippedImports, setSkippedImports] = useState<Array<{ path: string; reason: string }>>([]);

  async function prepareCastImport(directPaths?: string[]) {
    try {
      const paths = directPaths ?? (await chooseCastFiles());
      if (!paths.length) return;
      model.setTab("characters");
      const operation = model.editSession.capture();
      importOperation.current = operation;
      const preparation = await api.prepareCastImport(paths);
      const result = await commitUncontestedCastImport(preparation, (sessionId) => api.commitCastImport(sessionId, []));
      if (!result) return setCastImportPreparation(preparation);
      model.editSession.applyServer(operation, result.project);
      model.setNotice(castImportResultMessage(result.applied.length, result.skipped.length, preparation.errors.length, preparation.warnings));
      setSkippedImports(skippedCastImportReasons(preparation, result.skipped));
    } catch (error) {
      model.setNotice(`キャストを読み込めませんでした: ${(error as Error).message}`);
    }
  }
  const applyCastImportProject = (project: Parameters<typeof model.editSession.applyServer>[1]) => model.editSession.applyServer(importOperation.current, project);
  return { castImportPreparation, setCastImportPreparation, skippedImports, setSkippedImports, prepareCastImport, applyCastImportProject };
}
