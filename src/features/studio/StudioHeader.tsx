import { useRef, useState, type RefObject } from "react";
import { api } from "../../api";
import { HistoryActions } from "./HistoryActions";
import { StudioNotice } from "./StudioNotice";
import { DialogNoticeOverlay } from "../shared/DialogNoticeOverlay";
import { autoGenerationDisabled } from "./autoGenerationState";
import { disablePlaybackToggle, playbackToggleActive } from "./playbackHeaderState";
import { projectMenuActionDisabled } from "./projectMenuActions";
import { isTauriDevelopment } from "./isTauriDevelopment";
import { openStyleGuide } from "../styleguide/styleGuideNavigation";
import { loadCharactersView, loadDraftView, loadSettingsView } from "./secondaryTabLoaders";
import type { StudioController } from "./useStudioController";

export function ProjectMenu({ model }: { model: StudioController }) {
  const { busy, autoGenerateEnabled, workspace, requestProjectMenuAction } = model;
  const disabled = projectMenuActionDisabled(busy, autoGenerateEnabled);
  const workspaceSaved = workspace ? !workspace.isScratch : false;
  const [optimization, setOptimization] = useState<{ path: string; available: boolean } | null>(null);
  const statusRequest = useRef(0);
  const canOptimize = workspaceSaved && optimization?.path === workspace?.path && optimization?.available === true;
  function refreshOptimization() {
    if (!workspaceSaved || !workspace) return;
    const path = workspace.path;
    const request = ++statusRequest.current;
    setOptimization(null);
    void model.editSession
      .runServer(() => api.optimizationStatus())
      .then((status) => {
        if (request === statusRequest.current && status) setOptimization({ path, available: status.available });
      })
      .catch(() => {
        if (request === statusRequest.current) setOptimization({ path, available: false });
      });
  }
  return (
    <div className="project-menu">
      <button className="quiet-button header-action-button" disabled={disabled} onPointerEnter={refreshOptimization} onFocus={refreshOptimization}>
        <span className="header-button-label project-button-label">プロジェクト</span>
      </button>
      <div className="project-submenu" aria-label="プロジェクトメニュー">
        <button type="button" disabled={disabled} onClick={() => requestProjectMenuAction("new")}>
          <span className="project-menu-label">新規作成</span>
        </button>
        <button
          type="button"
          disabled={disabled || (workspaceSaved && !canOptimize)}
          onClick={() => {
            if (workspaceSaved) setOptimization(null);
            requestProjectMenuAction(workspaceSaved ? "optimize" : "save");
          }}
        >
          <span className="project-menu-label">{workspaceSaved ? "最適化保存" : "保存"}</span>
        </button>
        <button type="button" disabled={disabled} onClick={() => requestProjectMenuAction("open")}>
          <span className="project-menu-label">開く</span>
        </button>
        <button type="button" disabled={disabled} onClick={() => requestProjectMenuAction("script-import")}>
          <span className="project-menu-label">台本読み込み</span>
        </button>
        <button type="button" className="project-menu-ai" disabled={disabled} onClick={() => requestProjectMenuAction("ai-direction")}>
          <span className="project-menu-label">AI演出</span>
        </button>
        <button type="button" disabled={disabled} onClick={() => requestProjectMenuAction("lora-training")}>
          <span className="project-menu-label">LoRA管理…</span>
        </button>
        <div className="project-export-menu">
          <button className="project-export-trigger" type="button" aria-haspopup="menu" disabled={disabled}>
            <span className="project-menu-label">エクスポート</span>
            <span aria-hidden="true">▶</span>
          </button>
          <div className="project-export-submenu" role="menu" aria-label="エクスポートメニュー">
            <button role="menuitem" type="button" disabled={disabled} onClick={() => requestProjectMenuAction("export")}>
              音声・字幕・台本
            </button>
            <button role="menuitem" type="button" disabled={disabled} onClick={() => requestProjectMenuAction("project-backup")}>
              プロジェクト
            </button>
            <button role="menuitem" type="button" disabled={disabled} onClick={() => requestProjectMenuAction("cast-export")}>
              キャスト
            </button>
          </div>
        </div>
        <button type="button" className="danger" disabled={disabled} onClick={() => requestProjectMenuAction("clear-takes")}>
          <span className="project-menu-label project-menu-label-wide">生成テイク初期化</span>
        </button>
      </div>
    </div>
  );
}

function StudioTabs({ model }: { model: StudioController }) {
  const { tab, changeTab } = model;
  const tabButton = (id: typeof tab, label: string, preload?: () => unknown) => (
    <button className={tab === id ? "active" : ""} onPointerEnter={preload} onFocus={preload} onClick={() => changeTab(id)}>
      {label}
    </button>
  );
  return (
    <nav className="tabs" aria-label="画面切替">
      {tabButton("script", "台本")}
      {tabButton("characters", "キャスト", () => void loadCharactersView())}
      {tabButton("pronunciation", "辞書")}
      {tabButton("draft", "AI台本", () => void loadDraftView())}
      {tabButton("settings", "設定", () => void loadSettingsView())}
    </nav>
  );
}

export function StudioHeader({ model, headerRef }: { model: StudioController; headerRef: RefObject<HTMLDivElement | null> }) {
  const {
    tab,
    busy,
    exportJob,
    autoGenerateEnabled,
    continuousPlayback,
    autoScrollEnabled,
    autoScrollTarget,
    playbackHoverFollow,
    exportHoverFollow,
    enableAutoScroll,
    disablePlaybackHoverFollow,
    disableExportHoverFollow,
    playContinuous,
    stop,
    toggleAutoGeneration,
    historyScope,
    historyStatus,
    undo,
    redo,
    notice,
    noticeSerial,
    selectedLineGenerationActive,
    cancelSelectedLineGeneration,
  } = model;
  const playbackActive = playbackToggleActive(continuousPlayback);
  const playbackFollowActive = (autoScrollEnabled && autoScrollTarget === "playback") || playbackHoverFollow;
  const exportFollowActive = (autoScrollEnabled && autoScrollTarget === "export") || exportHoverFollow;
  const showStyleGuideLink = import.meta.env.DEV && isTauriDevelopment();
  return (
    <div ref={headerRef} className="app-header">
      <header className="topbar">
        <div className="brand">
          {showStyleGuideLink ? (
            <button type="button" className="brand-mark brand-mark--styleguide" aria-label="SCENA スタイルガイドを開く" title="SCENA スタイルガイド" onClick={openStyleGuide}>
              <span className="brand-illustration" aria-hidden="true" />
            </button>
          ) : (
            <span className="brand-mark" aria-hidden="true">
              <span className="brand-illustration" />
            </span>
          )}
          <span className="brand-wordmark-lockup" role="img" aria-label="irodori SCENA">
            <span className="brand-wordmark" aria-hidden="true" />
          </span>
        </div>
        <StudioTabs model={model} />
        <div className="header-actions">
          <HistoryActions scope={historyScope} status={historyStatus} onUndo={() => void undo()} onRedo={() => void redo()} />
          <ProjectMenu model={model} />
          <button
            className={`play-toggle header-action-button ${playbackActive ? "is-playing" : ""} ${playbackFollowActive ? "auto-scroll-active" : ""}`}
            aria-pressed={playbackActive}
            title="カーソルで選択された行から連続再生します。"
            disabled={disablePlaybackToggle(tab, busy, playbackActive)}
            onMouseEnter={() => enableAutoScroll("playback")}
            onMouseLeave={disablePlaybackHoverFollow}
            onClick={() => (playbackActive ? stop() : void playContinuous())}
          >
            <span className="header-button-label">{playbackActive ? "■ 停止" : "▶ 連続再生"}</span>
          </button>
          <button
            className={`export-button auto-generate-button ${busy === "export" ? "is-generating" : ""} ${autoGenerateEnabled ? "is-enabled" : ""} ${exportFollowActive ? "auto-scroll-active" : ""}`}
            disabled={autoGenerationDisabled(busy, Boolean(exportJob?.cancelRequested))}
            aria-pressed={autoGenerateEnabled}
            title="音声未生成の行を順番に自動生成します。"
            onMouseEnter={() => enableAutoScroll("export")}
            onMouseLeave={disableExportHoverFollow}
            onClick={toggleAutoGeneration}
          >
            <span className="auto-generate-status-icon" aria-hidden="true" />
            <span className="header-button-label">自動生成</span>
          </button>
        </div>
      </header>
      <StudioNotice busy={busy} text={notice} exportProgress={exportJob} cancellable={selectedLineGenerationActive} onCancel={() => void cancelSelectedLineGeneration()} />
      <DialogNoticeOverlay text={notice} serial={noticeSerial} busy={busy !== null} />
    </div>
  );
}
