/**
 * Inline input-check messages for dialogs. A check that fails at Save/Generate/Apply is shown next to
 * the control instead of the dialog notice overlay, so the owner can fix it without dismissing anything.
 * FieldError sits under the field at fault; FormError sits above the dialog footer for checks that
 * are not about one field.
 */
export function FieldError({ message, className = "" }: { message: string; className?: string }) {
  if (!message) return null;
  return (
    <small className={`field-error${className ? ` ${className}` : ""}`} role="alert">
      {message}
    </small>
  );
}

export function FormError({ message, className = "" }: { message: string; className?: string }) {
  if (!message) return null;
  return (
    <p className={`form-error${className ? ` ${className}` : ""}`} role="alert">
      {message}
    </p>
  );
}
