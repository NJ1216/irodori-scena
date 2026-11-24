import { api } from "../../api";

export async function completeProfileSuggestion(payload: Parameters<typeof api.startCharacterProfileSuggestion>[0], onProgress: (message: string) => void, options?: { signal?: AbortSignal; onStarted?: (jobId: string) => void }) {
  const job = await api.startCharacterProfileSuggestion(payload);
  options?.onStarted?.(job.id);
  onProgress(job.message);
  await api.characterProfileSuggestionEvents(
    job.id,
    (event) => {
      const message = (event.metrics as { message?: string }).message;
      if (message) onProgress(message);
    },
    { signal: options?.signal },
  );
  const completed = await api.characterProfileSuggestionJob(job.id);
  if (completed.status !== "completed" || !completed.result) {
    throw new Error(completed.error || completed.message);
  }
  return completed.result;
}

export class ProfileSuggestionSession {
  private readonly abort = new AbortController();
  private jobId: string | null = null;

  get cancelled() {
    return this.abort.signal.aborted;
  }

  complete(payload: Parameters<typeof api.startCharacterProfileSuggestion>[0], onProgress: (message: string) => void) {
    return completeProfileSuggestion(payload, onProgress, {
      signal: this.abort.signal,
      onStarted: (jobId) => {
        this.jobId = jobId;
        if (this.cancelled) void api.cancelCharacterProfileSuggestion(jobId).catch(() => undefined);
      },
    });
  }

  async cancel() {
    this.abort.abort();
    if (this.jobId) await api.cancelCharacterProfileSuggestion(this.jobId).catch(() => undefined);
  }
}
