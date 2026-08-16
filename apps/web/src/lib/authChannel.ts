export type AuthBroadcast =
  | { type: "signed-out" }
  | { type: "session-ended" }
  | { type: "session-renewed"; expiresAt: number };

const CHANNEL_NAME = "pp-auth";

let channel: BroadcastChannel | null | undefined;

function shared(): BroadcastChannel | null {
  if (channel !== undefined) return channel;
  if (typeof BroadcastChannel === "undefined") {
    channel = null;
    return channel;
  }
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
  } catch {
    channel = null;
  }
  return channel;
}

export function publishAuthEvent(message: AuthBroadcast): void {
  try {
    shared()?.postMessage(message);
  } catch {}
}

export function subscribeToAuthEvents(
  onMessage: (message: AuthBroadcast) => void,
): () => void {
  const target = shared();
  if (!target) return () => {};

  const handler = (event: MessageEvent<AuthBroadcast>) => onMessage(event.data);
  target.addEventListener("message", handler);
  return () => target.removeEventListener("message", handler);
}
