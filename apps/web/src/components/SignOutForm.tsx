import type { ReactNode } from "react";
import { beginSignOut } from "../api/auth";
import { publishAuthEvent } from "../lib/authChannel";

export default function SignOutForm({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <form
      method="post"
      action="/api/auth/logout"
      className={className}
      onSubmit={() => {
        beginSignOut();
        publishAuthEvent({ type: "signed-out" });
      }}
    >
      {children}
    </form>
  );
}
