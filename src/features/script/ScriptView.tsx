import { useState } from "react";
import { LineDragGhost } from "./LineDragGhost";
import { ScriptCanvas } from "./ScriptCanvas";
import { ScriptSpeakerRail } from "./ScriptSpeakerRail";
import { ScriptViewDialogs } from "./ScriptViewDialogs";
import type { ScriptViewProps } from "./ScriptViewTypes";
import { useLineReorderDrag } from "./useLineReorderDrag";
import { useScriptEditorKeyboard } from "./useScriptEditorKeyboard";

export function ScriptView(props: ScriptViewProps) {
  const [castSwitchOpen, setCastSwitchOpen] = useState(false);
  const [editingCastId, setEditingCastId] = useState<string | null>(null);
  const drag = useLineReorderDrag({ project: props.project, selectedLineIds: props.selectedLineIds, onSelect: props.onSelectDraggedLines, onMove: props.onMoveLines });
  const handleLineTextKeyDown = useScriptEditorKeyboard(props);
  return (
    <>
      <section className="workspace">
        <ScriptSpeakerRail project={props.project} onPlayReference={props.onPlayReference} playingReferenceCharacterId={props.playingReferenceCharacterId} onSettings={props.onSettings} onEditScriptContext={setEditingCastId} onOpenCastSwitch={() => setCastSwitchOpen(true)} />
        <ScriptCanvas view={props} rootRef={drag.rootRef} dragHandlers={drag.handlers} onKeyDown={handleLineTextKeyDown} />
        <LineDragGhost ghost={drag.ghost} />
      </section>
      <ScriptViewDialogs props={props} castSwitchOpen={castSwitchOpen} editingCastId={editingCastId} onCloseCastSwitch={() => setCastSwitchOpen(false)} onCloseCastContext={() => setEditingCastId(null)} />
    </>
  );
}
