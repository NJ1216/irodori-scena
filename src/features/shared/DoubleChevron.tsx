export function DoubleChevron({ className = "" }: { className?: string }) {
  return (
    <svg className={`double-chevron ${className}`.trim()} viewBox="0 0 16 12" aria-hidden="true">
      <path d="m3 2 5 4 5-4" />
      <path d="m3 6 5 4 5-4" />
    </svg>
  );
}
