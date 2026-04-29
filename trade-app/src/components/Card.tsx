import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function Card({ className, children, ...rest }: Props) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-6",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
