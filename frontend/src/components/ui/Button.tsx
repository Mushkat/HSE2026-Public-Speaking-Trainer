import { ButtonHTMLAttributes, forwardRef } from "react";

import "./Button.css";
import { cn } from "./utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  loading?: boolean;
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, children, variant = "primary", disabled, loading = false, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn("ui-button", `ui-button--${variant}`, className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <span className="ui-spinner" aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
});

export default Button;
