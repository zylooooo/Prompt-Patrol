import type {
  AppUser,
  CreateAccountInput,
  DeactivationOutcome,
  DeactivationPlan,
  LookupResult,
  SupervisionLink,
} from "../types";
import * as stub from "./stub";
import type { User } from "./auth";

export const userKeys = {
  all: ["users"] as const,
  list: () => [...userKeys.all, "list"] as const,
  supervision: () => [...userKeys.all, "supervision"] as const,
  myAssistants: () => [...userKeys.all, "mine"] as const,
};

export function listUsers(
  actor: User,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  return stub.listUsers(actor, signal);
}

export function listSupervision(
  signal?: AbortSignal,
): Promise<SupervisionLink[]> {
  return stub.listSupervision(signal);
}

export function listMyAssistants(
  actor: User,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  return stub.listMyAssistants(actor, signal);
}

export function createAccount(
  actor: User,
  input: CreateAccountInput,
): Promise<AppUser> {
  return stub.createAccount(actor, input);
}

export function linkSupervision(
  actor: User,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.linkSupervision(actor, instructorId, taId);
}

export function unlinkSupervision(
  actor: User,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.unlinkSupervision(actor, instructorId, taId);
}

export function setUserActive(
  actor: User,
  id: string,
  active: boolean,
): Promise<AppUser> {
  return stub.setUserActive(actor, id, active);
}

export function deactivateInstructor(
  actor: User,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  return stub.deactivateInstructor(actor, id, plan);
}

export function resendInvite(actor: User, id: string): Promise<void> {
  return stub.resendInvite(actor, id);
}

export const findUserById = stub.findUserById;
export const findUserByEmail = stub.findUserByEmail;
export const supervisorsOf = stub.supervisorsOf;
export const assistantsOf = stub.assistantsOf;
export const linkedAt = stub.linkedAt;
export const strandedBy = stub.strandedBy;

export function lookupForLinking(actor: User, email: string): LookupResult {
  return stub.lookupForLinking(actor, email);
}
