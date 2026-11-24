import { useState } from "react";
import type { ProjectMenuAction } from "./projectMenuActionTypes";

export function useProjectMenuActionState() {
  const [autoGenerationConflictAction, setAutoGenerationConflictAction] = useState<ProjectMenuAction | null>(null);
  return { autoGenerationConflictAction, setAutoGenerationConflictAction };
}
