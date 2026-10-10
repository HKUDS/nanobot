import * as React from "react";

import { formControlFocusClassName } from "@/components/ui/form-control";
import { cn } from "@/lib/utils";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  variant?: "default" | "search";
};

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, variant = "default", ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "touch-text-input flex h-10 w-full rounded-full border border-input bg-background px-3 py-2 text-sm file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
          variant === "search" || type === "search"
            ? "focus:outline-none" : formControlFocusClassName,
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

const SearchInput = React.forwardRef<HTMLInputElement, Omit<InputProps, "variant">>(
  (props, ref) => <Input {...props} ref={ref} variant="search" />,
);
SearchInput.displayName = "SearchInput";

export { Input, SearchInput };
