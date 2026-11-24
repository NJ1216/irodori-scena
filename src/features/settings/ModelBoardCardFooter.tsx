export function ModelBoardCardFooter({ isDefault, badge, metadata }: { isDefault: boolean; badge?: string; metadata: string }) {
  return (
    <span className="model-card-footer">
      <span className="model-card-badges">{(badge || isDefault) && <em>{badge || "既定"}</em>}</span>
      <span className="model-card-corner-meta" title={metadata}>
        {metadata}
      </span>
    </span>
  );
}
