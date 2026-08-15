import { useEffect } from "react";

export function usePageTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} · Prompt Patrol` : "Prompt Patrol";
    return () => {
      document.title = "Prompt Patrol";
    };
  }, [title]);
}
