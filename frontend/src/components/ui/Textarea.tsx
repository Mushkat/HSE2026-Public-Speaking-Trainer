import { forwardRef, TextareaHTMLAttributes } from "react";

import "./Input.css";
import "./Textarea.css";
import { cn } from "./utils";

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: string;
};

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, label, id, ...props },
  ref,
) {
  const textareaId = id ?? props.name;
  return (
    <label className="ui-field" htmlFor={textareaId}>
      {label ? <span className="ui-field__label">{label}</span> : null}
      <textarea ref={ref} id={textareaId} className={cn("ui-input ui-textarea", className)} {...props} />
    </label>
  );
});

export default Textarea;
