import type { SessionInfo } from "../api/auth";
import { publishAuthEvent } from "../lib/authChannel";
import { useCallback, useEffect, useRef, useState } from "react";

/** How close to the deadline before a ping is worth spending. */
const RENEW_WITHIN_MS = 5 * 60_000;
/** How long an interaction still counts as "they are still here". */
const ACTIVITY_WINDOW_MS = 60_000;
/** How long before the end the warning appears. */
const WARN_BEFORE_MS = 2 * 60_000;
/** Floor between renewal attempts, so a failing network is not hammered. */
const RENEW_COOLDOWN_MS = 20_000;

const RENEW_SHARE_OF_WINDOW = 0.25;
const WARN_SHARE_OF_WINDOW = 0.1;

function thresholdsFor(idleTimeoutSeconds: number) {
  const windowMs = Math.max(0, idleTimeoutSeconds) * 1000;
  if (windowMs === 0) {
    return { renewWithin: RENEW_WITHIN_MS, warnBefore: WARN_BEFORE_MS };
  }
  return {
    renewWithin: Math.min(RENEW_WITHIN_MS, windowMs * RENEW_SHARE_OF_WINDOW),
    warnBefore: Math.min(WARN_BEFORE_MS, windowMs * WARN_SHARE_OF_WINDOW),
  };
}

const ACTIVITY_EVENTS = [
  "pointerdown",
  "keydown",
  "wheel",
  "touchstart",
] as const;

export type SessionPhase = "ok" | "warning" | "expired";

interface Options {
  session: SessionInfo | null;
  /** Re-reads the session; resolves with the new deadline, or null if it ended. */
  onRenew: () => Promise<SessionInfo | null>;
  /** The deadline passed and the server could not be asked what to do. */
  onExpired: (capped: boolean) => void;
}

export interface SessionLifecycle {
  phase: SessionPhase;
  /** Whole seconds left. Only meaningful while `phase` is "warning". */
  secondsRemaining: number;
  /** True when the absolute cap ends this session, which nothing can postpone. */
  capped: boolean;
  isRenewing: boolean;
  /** Explicit "I am still here" from the warning dialog. */
  staySignedIn: () => void;
  /** Stops the warning re-appearing once acknowledged. */
  dismissWarning: () => void;
}

export function useSessionLifecycle({
  session,
  onRenew,
  onExpired,
}: Options): SessionLifecycle {
  const [phase, setPhase] = useState<SessionPhase>("ok");
  const [secondsRemaining, setSecondsRemaining] = useState(0);
  const [isRenewing, setIsRenewing] = useState(false);

  const lastActivityAt = useRef(0);
  const lastRenewAt = useRef(0);
  const renewing = useRef(false);
  const dismissed = useRef(false);
  const expiring = useRef(false);

  const onRenewRef = useRef(onRenew);
  const onExpiredRef = useRef(onExpired);
  useEffect(() => {
    onRenewRef.current = onRenew;
    onExpiredRef.current = onExpired;
  });

  const renew = useCallback(async () => {
    if (renewing.current) return;
    renewing.current = true;
    lastRenewAt.current = Date.now();
    setIsRenewing(true);
    try {
      const renewed = await onRenewRef.current();
      if (renewed) {
        publishAuthEvent({
          type: "session-renewed",
          expiresAt: renewed.expiresAt,
        });
      }
    } finally {
      renewing.current = false;
      setIsRenewing(false);
    }
  }, []);

  const staySignedIn = useCallback(() => {
    lastActivityAt.current = Date.now();
    dismissed.current = false;
    lastRenewAt.current = 0;
    void renew();
  }, [renew]);

  const dismissWarning = useCallback(() => {
    dismissed.current = true;
    setPhase("ok");
  }, []);

  useEffect(() => {
    const record = () => {
      lastActivityAt.current = Date.now();
    };
    record();
    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, record, { passive: true });
    }
    return () => {
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, record);
      }
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    dismissed.current = false;
    expiring.current = false;

    const { renewWithin, warnBefore } = thresholdsFor(
      session.idleTimeoutSeconds,
    );

    const evaluate = () => {
      const now = Date.now();
      const msLeft = session.expiresAt - now;

      if (msLeft <= 0) {
        setPhase("expired");
        if (!expiring.current) {
          expiring.current = true;
          onExpiredRef.current(session.capped);
        }
        return;
      }

      const stillHere = now - lastActivityAt.current <= ACTIVITY_WINDOW_MS;
      const cooledDown = now - lastRenewAt.current >= RENEW_COOLDOWN_MS;

      if (!session.capped && msLeft <= renewWithin && stillHere && cooledDown) {
        void renew();
        return;
      }

      if (msLeft <= warnBefore) {
        setSecondsRemaining(Math.max(0, Math.ceil(msLeft / 1000)));
        if (!dismissed.current) setPhase("warning");
        return;
      }
      setPhase("ok");
    };

    const firstPass = setTimeout(evaluate, 0);
    const timer = setInterval(evaluate, 1000);

    const onVisibility = () => {
      if (document.visibilityState === "visible") evaluate();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearTimeout(firstPass);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [session, renew]);

  return {
    phase: session ? phase : "ok",
    secondsRemaining,
    capped: session?.capped ?? false,
    isRenewing,
    staySignedIn,
    dismissWarning,
  };
}
