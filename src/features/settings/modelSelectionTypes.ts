import type { ReactNode } from "react";

export type ModelSelectionOption = {
  id: string;
  content: ReactNode;
  disabled?: boolean;
  onDetails?: () => void;
  detailsLabel?: string;
};

export type Placement = { left: number; top: number; width: number; cardWidth: number; maxHeight: number; above: boolean };
