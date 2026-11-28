import { useCallback, useMemo, useState } from "react";

export type InlineValidationError = { message: string; field?: string };

/** Field-scoped validation messages; the input carries `data-validation-field` so a failed check can focus it. */
export function useInlineValidation() {
  const [error, setError] = useState<InlineValidationError | null>(null);
  const report = useCallback((message: string, field?: string) => {
    setError({ message, field });
    if (field && typeof requestAnimationFrame === "function")
      requestAnimationFrame(() => {
        const target = document.querySelector<HTMLElement>(`[data-validation-field="${CSS.escape(field)}"]`);
        if (!target) return;
        // Centered so the field and its message are not left under a dialog's sticky header or footer.
        target.focus({ preventScroll: true });
        target.scrollIntoView?.({ block: "center" });
      });
  }, []);
  /** Clears the message of one field (when that field is edited), or every message when no field is given. */
  const clear = useCallback((field?: string) => setError((current) => (!current || field === undefined || current.field === field ? null : current)), []);
  /** Clears a message that is not about one field, keeping a field's message. */
  const clearForm = useCallback(() => setError((current) => (current && !current.field ? null : current)), []);
  return useMemo(
    () => ({
      report,
      clear,
      clearForm,
      fieldError: (field: string) => (error?.field === field ? error.message : ""),
      formError: error && !error.field ? error.message : "",
    }),
    [clear, clearForm, error, report],
  );
}

export type InlineValidation = ReturnType<typeof useInlineValidation>;
