import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

let fieldSeq = 0;
function nextId(prefix: string) {
  fieldSeq += 1;
  return `${prefix}-${fieldSeq}`;
}

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={["field", className ?? ""].filter(Boolean).join(" ")}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="field-hint">{hint}</p>}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextInput({
  id,
  label,
  hint,
  error,
  className,
  ...rest
}: { id?: string; label?: string; hint?: string; error?: string | null } & InputHTMLAttributes<HTMLInputElement>) {
  const fieldId = id ?? (label ? nextId("field") : undefined);
  const input = (
    <input id={fieldId} className={className} aria-invalid={error ? true : undefined} {...rest} />
  );
  if (!label) return input;
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      {input}
    </Field>
  );
}

export function TextArea({
  id,
  label,
  hint,
  error,
  className,
  ...rest
}: { id?: string; label?: string; hint?: string; error?: string | null } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const fieldId = id ?? (label ? nextId("field") : undefined);
  const area = (
    <textarea id={fieldId} className={className} aria-invalid={error ? true : undefined} {...rest} />
  );
  if (!label) return area;
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      {area}
    </Field>
  );
}
