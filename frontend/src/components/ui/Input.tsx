import { forwardRef, InputHTMLAttributes } from "react";

import "./Input.css";
import { cn } from "./utils";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
};

const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, label, hint, id, ...props }, ref) {
  const inputId = id ?? props.name;
  return (
    <label className="ui-field" htmlFor={inputId}>
      {label ? <span className="ui-field__label">{label}</span> : null}
      <input ref={ref} id={inputId} className={cn("ui-input", className)} {...props} />
      {hint ? <span className="ui-field__hint">{hint}</span> : null}
    </label>
  );
});

export default Input;
