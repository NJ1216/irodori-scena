import { useState } from "react";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { discardPendingProjectSaves, pauseProjectSaves, queueProjectSave, resumeProjectSaves, useProjectPersistenceState, waitForProjectPersistence } from "./projectPersistence";
import { inferSaveIntent } from "./projectSaveIntent";

export function useProjectEditSession(setNotice: (message: string) => void) {
  const [project, publish] = useState<StudioProject | null>(null);
  const persistence = useProjectPersistenceState();
  const model = { ...persistence, setNotice };
  const [editSession] = useState(() => {
    const session = new ProjectEditSession(publish);
    session.persistence = {
      save: (snapshot, message, failurePrefix) => {
        const operation = session.capture();
        return queueProjectSave(model, snapshot, message, failurePrefix, (saved) => session.recordSaved(operation, saved));
      },
      wait: () => waitForProjectPersistence(model),
      failureReason: () => model.projectSaveFailureReason.current,
      pause: () => pauseProjectSaves(model),
      resume: () => resumeProjectSaves(model),
      confirm: (snapshot) => {
        model.confirmedProject.current = snapshot;
      },
      rebasePending: (snapshot) => {
        const operation = session.capture();
        if (model.projectSavePending.current) {
          model.projectSavePending.current.snapshot = snapshot;
          model.projectSavePending.current.intent = inferSaveIntent(model.confirmedProject.current, snapshot);
          model.projectSavePending.current.onSaved = (saved) => session.recordSaved(operation, saved);
        }
      },
      discardPending: () => discardPendingProjectSaves(model),
    };
    return session;
  });
  return { project, editSession, projectRef: editSession.projectRef, pendingLineContentEdits: { current: editSession.pendingLines }, ...persistence };
}
