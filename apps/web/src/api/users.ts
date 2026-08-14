import type {
  AppUser,
  CreateAccountInput,
  DeactivationOutcome,
  DeactivationPlan,
  LookupResult,
  SupervisionLink,
} from "./types";
import * as stub from "./stub";

export const userKeys = {
  all: ["users"] as const,
  list: () => [...userKeys.all, "list"] as const,
  supervision: () => [...userKeys.all, "supervision"] as const,
  myAssistants: () => [...userKeys.all, "mine"] as const,
};

export function listUsers(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  return stub.listUsers(actorEmail, signal);
}

export function listSupervision(
  signal?: AbortSignal,
): Promise<SupervisionLink[]> {
  return stub.listSupervision(signal);
}

export function listMyAssistants(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  return stub.listMyAssistants(actorEmail, signal);
}

export function createAccount(
  actorEmail: string,
  input: CreateAccountInput,
): Promise<AppUser> {
  return stub.createAccount(actorEmail, input);
}

export function linkSupervision(
  actorEmail: string,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.linkSupervision(actorEmail, instructorId, taId);
}

export function unlinkSupervision(
  actorEmail: string,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.unlinkSupervision(actorEmail, instructorId, taId);
}

export function setUserActive(
  actorEmail: string,
  id: string,
  active: boolean,
): Promise<AppUser> {
  return stub.setUserActive(actorEmail, id, active);
}

export function deactivateInstructor(
  actorEmail: string,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  return stub.deactivateInstructor(actorEmail, id, plan);
}

export function resendInvite(actorEmail: string, id: string): Promise<void> {
  return stub.resendInvite(actorEmail, id);
}

export const findUserById = stub.findUserById;
export const findUserByEmail = stub.findUserByEmail;
export const supervisorsOf = stub.supervisorsOf;
export const assistantsOf = stub.assistantsOf;
export const linkedAt = stub.linkedAt;
export const strandedBy = stub.strandedBy;

export function lookupForLinking(
  actorEmail: string,
  email: string,
): LookupResult {
  return stub.lookupForLinking(actorEmail, email);
}
