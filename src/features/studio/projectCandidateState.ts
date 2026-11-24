import { api } from "../../api";
import type { ProjectEditSession } from "./projectEditSession";

export async function clearCandidateState(session: ProjectEditSession) {
  await session.runServer(async () => {
    const before = session.savedProject();
    if (before) session.update((project) => ({ ...project, candidates: [] }));
    const optimistic = session.capture();
    try {
      const project = await api.clearCandidates();
      session.applyServer(optimistic, project);
    } catch (error) {
      if (before) session.applyServer(optimistic, before);
      throw error;
    }
  });
}
