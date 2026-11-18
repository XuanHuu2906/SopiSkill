import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant =
  | "primary"
  | "dark"
  | "secondary"
  | "ghost"
  | "light"
  | "success"
  | "danger"
  | "text";

export type ButtonSize = "lg" | "md" | "sm";

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  children: ReactNode;
  className?: string;
};

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "",
  dark: "btn-dark",
  secondary: "btn-secondary",
  ghost: "btn-ghost",
  light: "btn-light",
  success: "btn-success",
  danger: "btn-danger",
  text: "btn-text",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  lg: "btn-lg",
  md: "btn-md",
  sm: "btn-sm",
};

function classes(variant: ButtonVariant, size: ButtonSize, block?: boolean, extra?: string) {
  return ["btn", VARIANT_CLASS[variant], SIZE_CLASS[size], block ? "btn-block" : "", extra ?? ""]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant = "primary",
  size = "lg",
  block,
  children,
  className,
  ...rest
}: CommonProps & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type={rest.type ?? "button"} className={classes(variant, size, block, className)} {...rest}>
      {children}
    </button>
  );
}

export function ButtonLink({
  variant = "primary",
  size = "lg",
  block,
  children,
  className,
  href,
  ...rest
}: CommonProps & { href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const cls = classes(variant, size, block, className);
  if (href.startsWith("http") || href.startsWith("#")) {
    return (
      <a className={cls} href={href} {...rest}>
        {children}
      </a>
    );
  }
  return (
    <Link className={cls} href={href} {...rest}>
      {children}
    </Link>
  );
}

export function IconButton({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={rest.type ?? "button"}
      className={["btn", "btn-icon", className ?? ""].filter(Boolean).join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}
