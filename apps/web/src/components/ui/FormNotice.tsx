import { CircleAlert, Info } from "lucide-react";
import type { ReactNode } from "react";

// One quiet line under a form row: an icon and text, no box. It sits outside
// the field labels so a message never changes a field's height, and the
// fields stay aligned.
const TONE = {
  error: { Icon: CircleAlert, className: "text-danger" },
  info: { Icon: Info, className: "text-muted-foreground" },
} as const;

interface FormNoticeProps {
  tone: keyof typeof TONE;
  id?: string;
  role?: "alert" | "status";
  children: ReactNode;
}

export default function FormNotice({
  tone,
  id,
  role,
  children,
}: FormNoticeProps) {
  const { Icon, className } = TONE[tone];
  return (
    <p
      id={id}
      role={role}
      className={`flex items-center gap-2 text-[13px] ${className}`}
    >
      <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}
