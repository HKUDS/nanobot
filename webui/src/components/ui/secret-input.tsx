import * as React from "react";
import { Eye, EyeOff } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const secretToggleClassName = "absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground";

type SecretInputProps = Omit<React.ComponentPropsWithoutRef<typeof Input>, "type"> & {
  visible: boolean;
  onToggle: () => void;
  toggleLabel: string;
  showToggle?: boolean;
  visibleType?: React.HTMLInputTypeAttribute;
  toggleClassName?: string;
  toggleControls?: string;
  iconClassName?: string;
  iconStrokeWidth?: number;
  children?: React.ReactNode;
};

/** Controlled presentation only; the caller owns the draft and its save lifecycle. */
export const SecretInput = React.forwardRef<HTMLInputElement, SecretInputProps>(
  ({
    visible, onToggle, toggleLabel, showToggle = true, visibleType = "text",
    toggleClassName = buttonVariants({ variant: "icon", size: "icon", className: secretToggleClassName }),
    toggleControls, iconClassName = "h-3.5 w-3.5", iconStrokeWidth, children, ...props
  }, ref) => {
    const Icon = visible ? EyeOff : Eye;
    return <div className="relative w-full">
      <Input {...props} ref={ref} type={visible ? visibleType : "password"} />
      {showToggle ? <button type="button" disabled={props.disabled} aria-label={toggleLabel}
        aria-controls={toggleControls} onClick={onToggle} className={toggleClassName}>
        <Icon className={iconClassName} strokeWidth={iconStrokeWidth} aria-hidden />
      </button> : null}
      {children}
    </div>;
  },
);
SecretInput.displayName = "SecretInput";
