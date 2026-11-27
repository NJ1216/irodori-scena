type StepHeadingProps = { number: number; children: string; level?: "h2" | "h3"; className?: string };

export function StepHeading({ number, children, level: Heading = "h2", className = "type-section-title draft-step-heading" }: StepHeadingProps) {
  return (
    <Heading className={className}>
      <span aria-hidden="true">
        <span className="circle-number-glyph">{number}</span>
      </span>
      {children}
    </Heading>
  );
}
