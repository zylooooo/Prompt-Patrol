import { useCallback, useSyncExternalStore } from "react";

const mqlCache = new Map<string, MediaQueryList>();

function getMql(query: string): MediaQueryList {
  let mql = mqlCache.get(query);
  if (!mql) {
    mql = window.matchMedia(query);
    mqlCache.set(query, mql);
  }
  return mql;
}

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      const mql = getMql(query);
      mql.addEventListener("change", onStoreChange);
      return () => mql.removeEventListener("change", onStoreChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => getMql(query).matches);
}
