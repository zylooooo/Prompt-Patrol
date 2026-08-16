import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { useCallback } from "react";
import SignOutForm from "./SignOutForm";
import { publishAuthEvent } from "../lib/authChannel";
import { useQueryClient } from "@tanstack/react-query";
import { sessionQueryOptions, useAuth } from "../hooks/useAuth";
import { useSessionLifecycle } from "../hooks/useSessionLifecycle";
import { getSession, type SessionInfo, type SessionState } from "../api/auth";

const MIN_USEFUL_REMAINING_MS = 5_000;

function formatCountdown(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export default function SessionSentinel() {
  const { session, refetch } = useAuth();
  const queryClient = useQueryClient();

  const onRenew = useCallback(async (): Promise<SessionInfo | null> => {
    const { data } = await refetch();
    return data?.status === "authenticated" ? data.session : null;
  }, [refetch]);

  const confirmExpiry = useCallback(
    async (capped: boolean) => {
      const state = await getSession(undefined, { probe: true }).catch(
        () => null,
      );

      const usable =
        state?.status === "authenticated" &&
        state.session.expiresAt - Date.now() > MIN_USEFUL_REMAINING_MS;

      if (usable) {
        queryClient.setQueryData(sessionQueryOptions().queryKey, state);
        return;
      }

      const ended: SessionState =
        state?.status === "anonymous"
          ? state
          : {
              status: "anonymous",
              reason: capped ? "session_ended" : "session_expired",
            };
      queryClient.setQueryData(sessionQueryOptions().queryKey, ended);
      publishAuthEvent({ type: "session-ended" });
    },
    [queryClient],
  );

  const onExpired = useCallback(
    (capped: boolean) => void confirmExpiry(capped),
    [confirmExpiry],
  );

  const {
    phase,
    secondsRemaining,
    capped,
    isRenewing,
    staySignedIn,
    dismissWarning,
  } = useSessionLifecycle({ session, onRenew, onExpired });

  if (phase !== "warning") return null;

  const countdown = formatCountdown(secondsRemaining);

  return (
    <Modal
      title={capped ? "Your session ends soon" : "Are you still there?"}
      onClose={dismissWarning}
      busy={isRenewing}
      footer={
        <>
          <SignOutForm>
            <Button type="submit" variant="secondary" disabled={isRenewing}>
              Sign out now
            </Button>
          </SignOutForm>
          {capped ? (
            <Button onClick={dismissWarning}>Keep working</Button>
          ) : (
            <Button onClick={staySignedIn} disabled={isRenewing}>
              {isRenewing ? "Staying signed in…" : "Stay signed in"}
            </Button>
          )}
        </>
      }
    >
      <p className="text-sm leading-6 text-muted-foreground">
        {capped ? (
          <>
            For security, a session lasts at most 12 hours, and this one reaches
            that limit in{" "}
            <strong className="font-semibold text-foreground">
              {countdown}
            </strong>
            . Signing in again is the only way to extend it, so finish anything
            you are part-way through now.
          </>
        ) : (
          <>
            You have not used Prompt Patrol for a while, so we will sign you out
            in{" "}
            <strong className="font-semibold text-foreground">
              {countdown}
            </strong>{" "}
            to keep your account safe on a shared machine. Anything you have
            typed and not run will be lost.
          </>
        )}
      </p>
    </Modal>
  );
}
