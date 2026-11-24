import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { DialogueLine, StudioProject } from "../../types";
import { downloadWav, lineTakeFileName, selectedTake } from "../shared/studio-utils";
import type { ScriptViewProps } from "./ScriptViewTypes";
import { scriptLineNumberMap } from "./scriptLineNumbers";
import { LineContextIcon } from "./LineContextIcon";
import { shortcutLabel } from "../shared/platform";

export type LineMenuState = { sourceId: string; ids: string[]; x: number; y: number };

export function LineContextMenu({ state, project, props, onClose }: { state: LineMenuState; project: StudioProject; props: ScriptViewProps; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: state.x, top: state.y });
  const all = project.scenes.flatMap((scene) => scene.lines);
  const source = all.find((line) => line.id === state.sourceId);
  const lines = state.ids.map((id) => all.find((line) => line.id === id)).filter((line): line is DialogueLine => Boolean(line));
  const seed = source ? (selectedTake(source)?.seed ?? source.manualSeed ?? source.fixedSeed) : undefined;
  const disabled = Boolean(props.busy || props.generatingLineId);
  const fixed = lines.filter((line) => line.fixedSeed !== undefined || line.manualSeed !== undefined);
  const unfixed = lines.filter((line) => line.fixedSeed === undefined && line.manualSeed === undefined);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    setPosition({ left: Math.max(8, Math.min(state.x, window.innerWidth - bounds.width - 8)), top: Math.max(8, Math.min(state.y, window.innerHeight - bounds.height - 8)) });
    element.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [state.x, state.y]);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [onClose]);
  if (!source) return null;
  const run = (action: () => unknown) => {
    onClose();
    void action();
  };
  const item = (label: string, icon: Parameters<typeof LineContextIcon>[0]["name"], action: () => unknown, disabled = false, shortcut?: string) => (
    <button type="button" role="menuitem" disabled={disabled} onClick={() => run(action)}>
      <LineContextIcon name={icon} />
      <span>{label}</span>
      {shortcut && (
        <kbd className="line-context-shortcut" aria-hidden="true">
          {shortcutLabel(shortcut)}
        </kbd>
      )}
    </button>
  );
  const saveWavs = async () => {
    let saved = 0;
    try {
      for (const line of lines) {
        const take = selectedTake(line);
        if (!take) continue;
        const number = scriptLineNumberMap(project).get(line.id) ?? 0;
        await downloadWav(take.audioUrl, lineTakeFileName(number, line.text));
        saved += 1;
      }
      props.onNotice(`${saved} 行のWAVを保存しました${lines.length > saved ? `（${lines.length - saved} 行は未生成）` : ""}。`);
    } catch (error) {
      props.onNotice(`${saved} 行を保存後に停止しました: ${(error as Error).message}`);
    }
  };
  return createPortal(
    <div
      ref={ref}
      className="line-context-menu"
      role="menu"
      aria-label="発話行の操作"
      style={position}
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        const buttons = [...ref.current!.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          buttons[(index + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length]?.focus();
        }
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          buttons[event.key === "Home" ? 0 : buttons.length - 1]?.focus();
        }
      }}
    >
      {item("新規テイク", "add", () => props.onGenerate("", source), disabled, "⌘⌥R")}
      {item("上書き生成", "replace", () => props.onRegenerate("", source), disabled, "⌘⇧R")}
      {item("AIで書き直す", "rewrite", () => props.onOpenRewriteAssistant(state.ids, state.sourceId), disabled)}
      <div className="line-context-menu-separator" role="separator" />
      {unfixed.length > 0 &&
        item(
          "Seedを固定",
          "seed",
          () =>
            props.onSetLineSeeds(
              unfixed.map((line) => line.id),
              { fixedSeed: seed },
            ),
          disabled || seed === undefined,
        )}
      {fixed.length > 0 &&
        item(
          "Seed固定を解除",
          "unfix",
          () =>
            props.onSetLineSeeds(
              fixed.map((line) => line.id),
              { fixedSeed: undefined, manualSeed: undefined },
            ),
          disabled,
        )}
      {item("WAVの保存", "download", saveWavs, !lines.some((line) => selectedTake(line)))}
      <div className="line-context-menu-separator" role="separator" />
      {item("未採用テイクの削除", "prune", () => props.onCleanupLineTakes(state.sourceId, "unselected"), disabled || !lines.some((line) => line.takes.some((take) => take.id !== line.selectedTakeId)))}
      {item("テイクの初期化", "clear", () => props.onCleanupLineTakes(state.sourceId, "all"), disabled || !lines.some((line) => line.takes.length))}
      {item("削除", "delete", () => props.onDeleteContextLines(state.sourceId), disabled, "Delete")}
    </div>,
    document.body,
  );
}
