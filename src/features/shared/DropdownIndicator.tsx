export function DropdownIndicator({ className }: { className?: string }) {
  return (
    <svg className={["dropdown-indicator", className].filter(Boolean).join(" ")} viewBox="0 0 12 8" aria-hidden="true">
      <path d="M0 0h12L6 8z" />
    </svg>
  );
}
