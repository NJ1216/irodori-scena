import { useRef, useState } from "react";
import { useNoticeState } from "./useNoticeState";
import type { DraftJob, ExportJob, LlmConnection, ProjectWorkspace } from "../../types";
import type { DecodedAudioPlayer } from "../shared/decodedAudioPlayer";
import { defaultLlmConnection, type AutoScrollTarget, type FocusedTextInput, type LineAssistantTarget, type Tab } from "./types";
import { useDraftComposerState } from "./useDraftComposerState";
import { useProjectEditSession } from "./useProjectEditSession";
import { useProjectMenuActionState } from "./useProjectMenuActionState";
import type { RenderJob } from "./renderJobQueue";
import type { SelectedLineGenerationBatch } from "./selectedLineGenerationBatch";

export function useProjectWorkspaceState() {
  const { notice, noticeSerial, setNotice, setStatusNotice } = useNoticeState("ローカルプロジェクトを読み込み中…");
  const projectSession = useProjectEditSession(setNotice);
  const [workspace, setWorkspace] = useState<ProjectWorkspace | null>(null);
  const [connection, setConnection] = useState<LlmConnection>(defaultLlmConnection);
  const [connectionReady, setConnectionReady] = useState(false);
  const tabRef = useRef<Tab>("script");
  const focusedTextInput = useRef<FocusedTextInput | null>(null);
  return { notice, noticeSerial, setNotice, setStatusNotice, ...projectSession, workspace, setWorkspace, connection, setConnection, connectionReady, setConnectionReady, tabRef, focusedTextInput };
}

export function useAutoGenerationState() {
  const autoGenerateEnabledRef = useRef(true);
  const autoGenerationRequestRef = useRef(0);
  const autoRenderQueue = useRef<RenderJob[]>([]);
  const autoRenderInProgress = useRef(false);
  const autoRenderPriorityActive = useRef(false);
  const autoRenderPriorityDepth = useRef(0);
  const autoRenderActiveLineId = useRef<string | null>(null);
  const playbackProtectedLineIds = useRef(new Set<string>());
  const selectedLineGenerationRun = useRef(0);
  const selectedLineGenerationTaskRef = useRef<Promise<void>>(Promise.resolve());
  const selectedLineGenerationCancelRef = useRef<() => Promise<void>>(async () => {});
  const selectedLineGenerationPauseRef = useRef<() => Promise<() => Promise<void>>>(async () => async () => {});
  const selectedLineGenerationBatchRef = useRef<SelectedLineGenerationBatch | null>(null);
  const [selectedLineGenerationActive, setSelectedLineGenerationActive] = useState(false);
  const selectedLinePlaybackStopRun = useRef(0);
  const selectedLinePlaybackPending = useRef(false);
  const processAutoRenderQueueRef = useRef<() => Promise<void>>(async () => {});
  const runWithAutoRenderPriorityRef = useRef(<T>(action: () => Promise<T>) => action());
  const reconcileAutoRenderQueueRef = useRef<(historyBaseRevision?: number) => void>(() => {});
  const stopRef = useRef<() => void>(() => {});
  const busyRef = useRef<string | null>(null);
  return {
    autoGenerateEnabledRef,
    autoGenerationRequestRef,
    autoRenderQueue,
    autoRenderInProgress,
    autoRenderPriorityActive,
    autoRenderPriorityDepth,
    autoRenderActiveLineId,
    playbackProtectedLineIds,
    selectedLineGenerationRun,
    selectedLineGenerationTaskRef,
    selectedLineGenerationCancelRef,
    selectedLineGenerationPauseRef,
    selectedLineGenerationBatchRef,
    selectedLineGenerationActive,
    setSelectedLineGenerationActive,
    selectedLinePlaybackStopRun,
    selectedLinePlaybackPending,
    processAutoRenderQueueRef,
    runWithAutoRenderPriorityRef,
    reconcileAutoRenderQueueRef,
    stopRef,
    busyRef,
  };
}

export function useDialogJobState() {
  const [tab, setTab] = useState<Tab>("script");
  const [settingsFocusRequested, setSettingsFocusRequested] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [autoGenerateEnabled, setAutoGenerateEnabled] = useState(true);
  const [draftJob, setDraftJob] = useState<DraftJob | null>(null);
  const [draftCompletionSummary, setDraftCompletionSummary] = useState<DraftJob | null>(null);
  const [draftComposer, setDraftComposer] = useDraftComposerState();
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const exportUpdateVersion = useRef(0);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [castExportDialogOpen, setCastExportDialogOpen] = useState(false);
  const [scriptImportOpen, setScriptImportOpen] = useState(false);
  const [aiDirectionOpen, setAiDirectionOpen] = useState(false);
  const [wavSaveConfirmOpen, setWavSaveConfirmOpen] = useState(false);
  const [projectMaintenanceAction, setProjectMaintenanceAction] = useState<"new" | "takes" | null>(null);
  const projectMenuActionState = useProjectMenuActionState();
  const [globalCastUpdates, setGlobalCastUpdates] = useState<Array<{ id: string; name: string }> | null>(null);
  const [clearTakesConfirm, setClearTakesConfirm] = useState(false);
  const [lineAssistantTarget, setLineAssistantTarget] = useState<LineAssistantTarget | null>(null);
  return {
    tab,
    setTab,
    settingsFocusRequested,
    setSettingsFocusRequested,
    busy,
    setBusy,
    autoGenerateEnabled,
    setAutoGenerateEnabled,
    draftJob,
    setDraftJob,
    draftCompletionSummary,
    setDraftCompletionSummary,
    draftComposer,
    setDraftComposer,
    exportJob,
    setExportJob,
    exportUpdateVersion,
    exportDialogOpen,
    setExportDialogOpen,
    castExportDialogOpen,
    setCastExportDialogOpen,
    scriptImportOpen,
    setScriptImportOpen,
    aiDirectionOpen,
    setAiDirectionOpen,
    wavSaveConfirmOpen,
    setWavSaveConfirmOpen,
    projectMaintenanceAction,
    setProjectMaintenanceAction,
    ...projectMenuActionState,
    globalCastUpdates,
    setGlobalCastUpdates,
    clearTakesConfirm,
    setClearTakesConfirm,
    lineAssistantTarget,
    setLineAssistantTarget,
  };
}

function useSyncedArrayState<T>() {
  const current = useRef<T[]>([]);
  const [value, setValueState] = useState<T[]>([]);
  const setValue = (next: T[]) => {
    current.current = next;
    setValueState(next);
  };
  return [value, current, setValue] as const;
}

export function usePlaybackSelectionState() {
  const stopPlayback = useRef(false);
  const activeAudio = useRef<DecodedAudioPlayer | null>(null);
  const resolveActivePlayback = useRef<(() => void) | null>(null);
  const playbackRun = useRef(0);
  const continuousPlaybackWaiters = useRef(new Set<() => void>());
  const [continuousPlayback, setContinuousPlayback] = useState(false);
  const [focusedLineId, setFocusedLineId] = useState<string | null>(null);
  const [selectedLineIds, selectedLineIdsRef, setSelectedLineIds] = useSyncedArrayState<string>();
  const [selectionAnchorLineId, setSelectionAnchorLineId] = useState<string | null>(null);
  const [batchGeneratingLineId, setBatchGeneratingLineId] = useState<string | null>(null);
  const [playingLineId, setPlayingLineId] = useState<string | null>(null);
  const [playingReferenceCharacterId, setPlayingReferenceCharacterId] = useState<string | null>(null);
  return {
    stopPlayback,
    activeAudio,
    resolveActivePlayback,
    playbackRun,
    continuousPlaybackWaiters,
    continuousPlayback,
    setContinuousPlayback,
    focusedLineId,
    setFocusedLineId,
    selectedLineIds,
    selectedLineIdsRef,
    setSelectedLineIds,
    selectionAnchorLineId,
    setSelectionAnchorLineId,
    batchGeneratingLineId,
    setBatchGeneratingLineId,
    playingLineId,
    setPlayingLineId,
    playingReferenceCharacterId,
    setPlayingReferenceCharacterId,
  };
}

export function useScrollFocusState() {
  const [autoScrollTarget, setAutoScrollTarget] = useState<AutoScrollTarget>("playback");
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(false);
  const [playbackHoverFollow, setPlaybackHoverFollow] = useState(false);
  const [exportHoverFollow, setExportHoverFollow] = useState(false);
  return { autoScrollTarget, setAutoScrollTarget, autoScrollEnabled, setAutoScrollEnabled, playbackHoverFollow, setPlaybackHoverFollow, exportHoverFollow, setExportHoverFollow };
}
