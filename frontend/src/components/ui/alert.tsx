import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative flex w-full gap-3 rounded-lg border p-4 text-sm [&>svg]:mt-0.5 [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-border bg-background text-foreground [&>svg]:text-foreground",
        destructive:
          "border-red-200 bg-red-50 text-red-900 [&>svg]:text-red-600",
        warning: "border-amber-200 bg-amber-50 text-amber-900 [&>svg]:text-amber-600",
        success: "border-emerald-200 bg-emerald-50 text-emerald-900 [&>svg]:text-emerald-600",
        info: "border-sky-200 bg-sky-50 text-sky-900 [&>svg]:text-sky-600",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

const alertIcons = {
  default: Info,
  destructive: XCircle,
  warning: AlertTriangle,
  success: CheckCircle2,
  info: Info,
} as const;

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  showIcon?: boolean;
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant, showIcon = true, children, ...props }, ref) => {
    const Icon = alertIcons[variant ?? "default"];
    return (
      <div ref={ref} role="alert" className={cn(alertVariants({ variant }), className)} {...props}>
        {showIcon ? <Icon aria-hidden="true" /> : null}
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    );
  },
);
Alert.displayName = "Alert";

const AlertTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h5 ref={ref} className={cn("mb-1 font-medium leading-none", className)} {...props} />
  ),
);
AlertTitle.displayName = "AlertTitle";

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("text-sm leading-relaxed", className)} {...props} />
));
AlertDescription.displayName = "AlertDescription";

export { Alert, AlertTitle, AlertDescription };
