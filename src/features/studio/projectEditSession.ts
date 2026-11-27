import type { DialogueLine, StudioProject } from "../../types";
import { mergeProjectValue } from "./projectSessionMerge";

export type ProjectOperation = { projectId: string | null; generation: number; editVersion: number; base: StudioProject | null };
type Persistence = {
  save: (snapshot: StudioProject, message: string, failurePrefix?: string) => Promise<boolean>;
  wait: () => Promise<boolean>;
  failureReason?: () => string | null;
  pause: () => void;
  resume: () => void;
  discardPending?: () => void;
  rebasePending: (snapshot: StudioProject) => void;
  confirm?: (snapshot: StudioProject | null) => void;
};
const contentFields = ["text", "stageDirection", "pronunciations"] as const;
function linePatch(project: StudioProject, lineId: string, patch: Partial<DialogueLine>): StudioProject {
  return { ...project, scenes: project.scenes.map((scene) => ({ ...scene, lines: scene.lines.map((line) => (line.id === lineId ? { ...line, ...patch } : line)) })) };
}

export class ProjectEditSession {
  private committed: StudioProject | null = null;
  private generation = 0;
  private editVersion = 0;
  private drafts = new Map<string, Partial<DialogueLine>>();
  private serverTail: Promise<void> = Promise.resolve();
  readonly pendingLines = new Set<string>();
  readonly projectRef: { readonly current: StudioProject | null };
  persistence?: Persistence;
  serverRevision = 0;

  constructor(private readonly publish: (project: StudioProject | null) => void) {
    const read = () => this.withDrafts();
    this.projectRef = {
      get current() {
        return read();
      },
    };
  }

  capture = (): ProjectOperation => ({ projectId: this.committed?.id ?? null, generation: this.generation, editVersion: this.editVersion, base: this.committed });
  isCurrent = (operation: ProjectOperation) => operation.projectId === (this.committed?.id ?? null) && operation.generation === this.generation;
  savedProject = () => this.committed;

  private withDrafts() {
    let next = this.committed;
    if (next) for (const [lineId, patch] of this.drafts) next = linePatch(next, lineId, patch);
    return next;
  }

  private emit() {
    this.publish(this.committed);
  }

  replace = (project: StudioProject | null) => {
    this.persistence?.discardPending?.();
    this.generation += 1;
    this.editVersion += 1;
    this.committed = project;
    this.persistence?.confirm?.(project);
    this.serverRevision = project?.revision ?? 0;
    this.drafts.clear();
    this.pendingLines.clear();
    this.emit();
  };

  update = (mutator: (project: StudioProject) => StudioProject) => {
    if (!this.committed) return;
    this.committed = mutator(this.committed);
    this.editVersion += 1;
    this.emit();
  };

  draftLine = (lineId: string, patch: Partial<DialogueLine>) => {
    if (!this.committed) return;
    this.drafts.set(lineId, { ...this.drafts.get(lineId), ...patch });
    this.pendingLines.add(lineId);
    this.editVersion += 1;
  };

  updateLine = (lineId: string, patch: Partial<DialogueLine>) => {
    const content = contentFields.some((key) => Object.hasOwn(patch, key));
    if (content) this.draftLine(lineId, patch);
    else this.update((current) => linePatch(current, lineId, patch));
    return content;
  };

  commitLine = (lineId: string) => {
    const patch = this.drafts.get(lineId);
    if (!patch || !this.committed) return false;
    this.drafts.delete(lineId);
    this.pendingLines.delete(lineId);
    this.update((current) => linePatch(current, lineId, patch));
    return true;
  };

  applyServer = (operation: ProjectOperation, project: StudioProject) => {
    if (!this.isCurrent(operation) || project.id !== operation.projectId) return false;
    this.committed = operation.editVersion === this.editVersion && operation.base === this.committed ? project : (mergeProjectValue(operation.base, this.committed, project) as StudioProject);
    this.serverRevision = Math.max(this.serverRevision, project.revision ?? 0);
    this.committed = { ...this.committed, revision: this.serverRevision };
    this.persistence?.rebasePending(this.committed);
    this.emit();
    return true;
  };

  applyServerUpdate = (operation: ProjectOperation, mutator: (project: StudioProject) => StudioProject) => {
    if (!operation.base) return false;
    return this.applyServer(operation, mutator(operation.base));
  };

  restore = (operation: ProjectOperation, project: StudioProject) => {
    if (!this.applyServer(operation, project)) return false;
    // History restores the JSON preimage, including its older server revision.
    // The next save must use that restored revision as its concurrency base.
    this.serverRevision = project.revision ?? 0;
    if (this.committed) this.committed = { ...this.committed, revision: this.serverRevision };
    this.persistence?.confirm?.(project);
    this.generation += 1;
    if (this.committed) {
      this.persistence?.rebasePending(this.committed);
      this.emit();
    }
    return true;
  };

  recordSaved = (operation: ProjectOperation, project: StudioProject) => {
    this.applyServer(operation, project);
  };

  save = (message = "保存しました", failurePrefix?: string) => {
    if (!this.committed || !this.persistence) return Promise.resolve(false);
    return this.persistence.save(this.committed, message, failurePrefix);
  };
  waitForPersistence = () => this.persistence?.wait() ?? Promise.resolve(true);

  // Explicit user actions (Save, continuous playback) recover a failed save by re-queueing the
  // committed on-screen project once, silently; no background retry is scheduled. The queue
  // rebases on the server project from a revision conflict, so the re-send overwrites it.
  retryFailedSave = async () => {
    if (await this.waitForPersistence()) return true;
    if (!this.committed || !this.persistence) return false;
    return this.persistence.save(this.committed, "");
  };

  runServer = async <T>(action: (operation: ProjectOperation) => Promise<T>, reflect?: (result: T, operation: ProjectOperation) => void): Promise<T | undefined> => {
    const requested = this.capture();
    const preceding = this.serverTail;
    let release = () => {};
    this.serverTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    try {
      await preceding;
      if (!this.isCurrent(requested)) return;
      if (!(await this.waitForPersistence())) throw new Error(this.persistence?.failureReason?.() ?? "保存できませんでした");
      if (!this.isCurrent(requested)) return;
      const operation = this.capture();
      this.persistence?.pause();
      try {
        const result = await action(operation);
        if (!this.isCurrent(operation)) return;
        reflect?.(result, operation);
        return result;
      } finally {
        this.persistence?.resume();
      }
    } catch (error) {
      if (!this.isCurrent(requested)) return;
      throw error;
    } finally {
      release();
    }
  };

  requestUpdate = <T>(action: () => Promise<T>, update: (project: StudioProject, result: T) => StudioProject) =>
    this.runServer(action, (result, operation) => {
      this.applyServerUpdate(operation, (project) => update(project, result));
    });

  optimisticProject = (action: () => Promise<StudioProject>, update: (project: StudioProject) => StudioProject, replace = false) =>
    this.runServer(
      async () => {
        const before = this.committed;
        this.update(update);
        const operation = this.capture();
        try {
          const result = await action();
          if (!this.isCurrent(operation)) return;
          if (!replace) this.applyServer(operation, result);
          return result;
        } catch (error) {
          if (before) this.applyServer(operation, before);
          throw error;
        }
      },
      (result) => {
        if (replace && result) this.replace(result);
      },
    );

  switchProject = (action: () => Promise<StudioProject>) => this.runServer(action, (project) => this.replace(project));

  requestProject = (action: () => Promise<StudioProject>) =>
    this.runServer(action, (project, operation) => {
      this.applyServer(operation, project);
    });
}
