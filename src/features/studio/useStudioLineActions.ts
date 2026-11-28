import { api } from "../../api";
import type { DialogueLine, LineGenerationResult, Take } from "../../types";
import { nextId, sceneLabel, selectedTake } from "../shared/studio-utils";
import type { StudioProjectEditingActions } from "./useStudioProjectEditing";
import type { StudioState } from "./useStudioState";
import { wakeContinuousPlaybackWaiters } from "./continuousPlaybackWait";

type LineModel = Pick<StudioState, "project" | "editSession" | "setNotice" | "setStatusNotice" | "busy" | "setBusy" | "setLineAssistantTarget" | "setFocusedLineId" | "setSelectedLineIds" | "setSelectionAnchorLineId" | "playingLineId" | "stopRef" | "continuousPlaybackWaiters" | "autoRenderActiveLineId"> & {
  autoGenerateEnabledRef?: { current: boolean };
} & Pick<StudioProjectEditingActions, "updateProject" | "queueAutoRender">;

function waitForPaint() {
  return new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

async function switchProjectCharacters(model: Pick<LineModel, "project" | "stopRef" | "setBusy" | "setNotice" | "editSession">, mappings: Array<{ fromCharacterId: string; toCharacterId: string }>) {
  if (!model.project || !mappings.length) return;
  model.stopRef.current();
  model.setBusy("switch-characters");
  try {
    const result = await model.editSession.runServer(
      () => api.switchCharacters(mappings),
      (value, operation) => {
        model.editSession.applyServer(operation, value.project);
      },
    );
    if (!result) return;
    model.setNotice(`${result.invalidatedLines} 行のキャストを同時に切り替えました。旧テイクの選択は解除されています。`);
  } catch (error) {
    model.setNotice(`キャストを一括切り替えできませんでした: ${(error as Error).message}`);
    throw error;
  } finally {
    model.setBusy(null);
  }
}

// eslint-disable-next-line max-lines-per-function
export function useStudioLineActions(model: LineModel) {
  const { project, setNotice, setStatusNotice, busy, setBusy, setLineAssistantTarget, setFocusedLineId, setSelectedLineIds, setSelectionAnchorLineId, playingLineId, stopRef, updateProject, queueAutoRender } = model;
  async function changeLineCharacter(line: DialogueLine, characterId: string) {
    if (line.characterId === characterId) return;
    if (playingLineId === line.id) stopRef.current();
    setBusy(line.id);
    try {
      const next = await model.editSession.requestProject(() => api.changeLineCharacter(line.id, characterId));
      if (!next) return;
      setNotice("キャストを変更しました。");
    } catch (error) {
      setNotice(`キャストを変更できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function switchCharacters(mappings: Array<{ fromCharacterId: string; toCharacterId: string }>) {
    return switchProjectCharacters(model, mappings);
  }

  function applyGeneratedTake(sceneId: string, lineId: string, result: LineGenerationResult, replace = false, operation = model.editSession.capture()) {
    const { take, projectRevision } = result;
    model.editSession.applyServerUpdate(operation, (current) => ({
      ...current,
      revision: projectRevision,
      scenes: current.scenes.map((scene) =>
        scene.id !== sceneId
          ? scene
          : {
              ...scene,
              lines: scene.lines.map((line) =>
                line.id !== lineId
                  ? line
                  : {
                      ...line,
                      takes: replace ? line.takes.map((item) => (item.id === take.id ? take : item)) : line.takes.some((item) => item.id === take.id) ? line.takes : [...line.takes, take],
                      selectedTakeId: take.id,
                    },
              ),
            },
      ),
    }));
    wakeContinuousPlaybackWaiters(model.continuousPlaybackWaiters);
  }

  async function addLine(sceneId: string, beforeLineId?: string) {
    if (busy) {
      setNotice("実行中の処理が完了してから発話行を追加してください。");
      return;
    }
    setBusy("insert-line");
    try {
      const next = await model.editSession.requestProject(() => api.insertLine(sceneId, beforeLineId));
      if (!next) return;
      const insertedScene = next.scenes.find((scene) => scene.id === sceneId);
      const insertedIndex = beforeLineId ? insertedScene?.lines.findIndex((line) => line.id === beforeLineId) : (insertedScene?.lines.length ?? 1);
      const insertedLine = insertedScene?.lines[(insertedIndex ?? 1) - 1];
      if (insertedLine) {
        setFocusedLineId(insertedLine.id);
        setSelectedLineIds([insertedLine.id]);
        setSelectionAnchorLineId(insertedLine.id);
        window.requestAnimationFrame(() => {
          document.querySelector<HTMLElement>(`article[data-line-id="${insertedLine.id}"] .line-text-editor`)?.focus();
        });
      }
      setNotice(beforeLineId ? "発話行を挿入しました。" : "発話行を追加しました。");
    } catch (error) {
      setNotice(`発話行を追加できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function splitLine(sceneId: string, lineId: string, offset: number) {
    if (busy && busy !== model.autoRenderActiveLineId.current) {
      setNotice("実行中の処理が完了してから発話行を分割してください。");
      return false;
    }
    setBusy("insert-line");
    try {
      const existingIds = new Set(project?.scenes.find((scene) => scene.id === sceneId)?.lines.map((line) => line.id));
      const next = await model.editSession.requestProject(() => api.splitLine(sceneId, lineId, offset));
      if (!next) return false;
      const insertedLine = next.scenes.find((scene) => scene.id === sceneId)?.lines.find((line) => !existingIds.has(line.id));
      if (insertedLine) {
        setFocusedLineId(insertedLine.id);
        setSelectedLineIds([insertedLine.id]);
        setSelectionAnchorLineId(insertedLine.id);
        window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`article[data-line-id="${insertedLine.id}"] .line-text-editor`)?.focus());
      }
      setNotice("カーソル位置で発話行を分割しました。");
      return true;
    } catch (error) {
      setNotice(`発話行を分割できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function addCueMember(sceneId: string, line: DialogueLine, characterId: string) {
    if (busy) return setNotice("実行中の処理が完了してから同時話者を追加してください。");
    setBusy("add-cue-member");
    try {
      const next = await model.editSession.requestProject(() => api.addCueMember(sceneId, line.id, characterId));
      if (!next) return;
      setNotice("同時話者を追加しました。");
    } catch (error) {
      setNotice(`同時話者を追加できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  function openLineAssistant(sceneId: string, beforeLineId?: string) {
    if (busy) {
      setNotice("実行中の処理が完了してからAIに行追加を依頼してください。");
      return;
    }
    if (!project?.characters.length) {
      setNotice("先にキャストを登録してください。");
      return;
    }
    setLineAssistantTarget({ kind: "insert", sceneId, beforeLineId });
  }

  function addScene(beforeSceneId?: string, withInitialLine = false) {
    const sceneId = nextId("scene");
    const lineId = withInitialLine ? nextId("line") : null;
    updateProject(
      (current) => {
        const scene = {
          id: sceneId,
          title: `Scene ${sceneLabel(current.scenes.length)}`,
          lines: lineId
            ? [
                {
                  id: lineId,
                  characterId: current.characters[0]?.id ?? "",
                  text: "",
                  stageDirection: "",
                  takes: [],
                  selectedTakeId: null,
                },
              ]
            : [],
        };
        const beforeIndex = beforeSceneId ? current.scenes.findIndex((item) => item.id === beforeSceneId) : -1;
        return {
          ...current,
          scenes: beforeIndex >= 0 ? [...current.scenes.slice(0, beforeIndex), scene, ...current.scenes.slice(beforeIndex)] : [...current.scenes, scene],
        };
      },
      withInitialLine ? "シーンと発話行を追加しました" : beforeSceneId ? "シーンを挿入しました" : "シーンを追加しました",
    );
    if (lineId) {
      setFocusedLineId(lineId);
      setSelectedLineIds([lineId]);
      setSelectionAnchorLineId(lineId);
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLElement>(`article[data-line-id="${lineId}"] .line-text-editor`)?.focus();
      });
    }
  }

  async function generateLine(sceneId: string, line: DialogueLine) {
    if (busy === "draft" || busy === "export") {
      setNotice(busy === "draft" ? "AI台本の生成中は音声合成を開始できません。" : "まとめてエクスポート中は音声合成を開始できません。");
      return false;
    }
    if (!project || !line.text.trim()) {
      setNotice("先に本文を入力してください。");
      return false;
    }
    if (!line.characterId) {
      setNotice("キャストを選んでください。");
      return false;
    }
    if (model.autoGenerateEnabledRef?.current) {
      queueAutoRender(line.id, { mode: "append", cause: "manual-new-take" });
      setNotice("新規テイクを生成キューの先頭へ追加しました。");
      return true;
    }
    setBusy(line.id);
    setNotice("Irodori-TTSで生成中です…");
    try {
      await waitForPaint();
      const take = await model.editSession.runServer(
        () => api.generateLine(line.id, project.settings.quality),
        (value, operation) => applyGeneratedTake(sceneId, line.id, value, false, operation),
      );
      if (!take) return false;
      setStatusNotice("新しいテイクを生成しました。");
      return true;
    } catch (error) {
      setNotice(`生成できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function generateTakeWithSeed(sceneId: string, line: DialogueLine, seed: number) {
    if (busy === "draft" || busy === "export") {
      setNotice(busy === "draft" ? "AI台本の生成中は音声合成を開始できません。" : "まとめてエクスポート中は音声合成を開始できません。");
      return false;
    }
    if (!project || !line.text.trim()) {
      setNotice("先に本文を入力してください。");
      return false;
    }
    if (!line.characterId) {
      setNotice("キャストを選んでください。");
      return false;
    }
    if (model.autoGenerateEnabledRef?.current) {
      queueAutoRender(line.id, { mode: "append", cause: "manual-seed", seed });
      setNotice(`Seed ${seed} のテイクを生成キューの先頭へ追加しました。`);
      return true;
    }
    setBusy(line.id);
    setNotice(`Seed ${seed} でテイクを生成中です…`);
    try {
      await waitForPaint();
      const take = await model.editSession.runServer(
        () => api.generateLine(line.id, project.settings.quality, false, seed),
        (value, operation) => applyGeneratedTake(sceneId, line.id, value, false, operation),
      );
      if (!take) return false;
      setStatusNotice(`Seed ${seed} で新しいテイクを追加しました。`);
      return true;
    } catch (error) {
      setNotice(`Seed指定のテイクを生成できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function regenerateLine(sceneId: string, line: DialogueLine) {
    if (!project || !selectedTake(line)) {
      setNotice("上書きするテイクを選択してください。");
      return false;
    }
    if (!line.text.trim() || !line.characterId) {
      setNotice("本文とキャストを設定してから再生成してください。");
      return false;
    }
    if (model.autoGenerateEnabledRef?.current) {
      queueAutoRender(line.id, { mode: "replace", cause: "manual-replace", targetTakeId: line.selectedTakeId ?? undefined });
      setNotice("選択テイクの上書きを生成キューの先頭へ追加しました。");
      return true;
    }
    if (busy === "draft" || busy === "export") {
      setNotice("実行中の処理が完了してから再生成してください。");
      return false;
    }
    if (playingLineId === line.id) stopRef.current();
    setBusy(line.id);
    setNotice("選択テイクを上書き生成中です…");
    try {
      await waitForPaint();
      const take = await model.editSession.runServer(
        () => api.regenerateLine(line.id, project.settings.quality),
        (value, operation) => applyGeneratedTake(sceneId, line.id, value, true, operation),
      );
      if (!take) return false;
      setStatusNotice("選択テイクを上書き再生成しました。");
      return true;
    } catch (error) {
      setNotice(`再生成できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function deleteTake(line: DialogueLine, take: Take) {
    if (playingLineId === line.id) stopRef.current();
    const exporting = busy === "export";
    if (!exporting) setBusy(line.id);
    try {
      const next = await model.editSession.requestProject(() => api.deleteTake(line.id, take.id));
      if (!next) return;
      if (!exporting && next.scenes.flatMap((scene) => scene.lines).find((item) => item.id === line.id)?.takes.length === 0) {
        queueAutoRender(line.id, { mode: "append", cause: "last-take-deleted" });
      }
      setNotice(exporting ? "テイクを削除しました。エクスポートキューでこの行を再生成します。" : "テイクを削除しました。");
    } catch (error) {
      setNotice(`テイクを削除できませんでした: ${(error as Error).message}`);
    } finally {
      if (!exporting) setBusy(null);
    }
  }

  return {
    changeLineCharacter,
    switchCharacters,
    applyGeneratedTake,
    addLine,
    splitLine,
    addCueMember,
    openLineAssistant,
    addScene,
    generateLine,
    generateTakeWithSeed,
    regenerateLine,
    deleteTake,
  };
}

export type StudioLineActions = ReturnType<typeof useStudioLineActions>;
