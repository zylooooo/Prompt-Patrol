import DataTable, {
  TABLE_ACTIONS_LABELLED_COLUMN_WIDTH,
  TABLE_STATUS_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import {
  useAddTeachingAssistant,
  useMyAssistants,
  useResendInvite,
  useUnlinkSupervisor,
} from "../hooks/useUsers";
import { useAuth } from "../hooks/useAuth";
import { useState } from "react";
import { ApiError } from "../api/client";
import Modal from "../components/ui/Modal";
import { fmtDateOnly } from "../lib/format";
import { useToast } from "../hooks/useToast";
import Button from "../components/ui/Button";
import RowAction from "../components/ui/RowAction";
import RowActionMenu from "../components/ui/RowActionMenu";
import EmailTypoHint from "../components/ui/EmailTypoHint";
import FormNotice from "../components/ui/FormNotice";
import { useEmailTypoGuard } from "../hooks/useEmailTypoGuard";
import ErrorState from "../components/ui/ErrorState";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import {
  displayName,
  isPending as isPendingInvite,
  type AppUser,
} from "../types";
import Page, { PageFill } from "../components/ui/Page";
import UserStatusChip from "../components/ui/UserStatusChip";
import { SECTION_LABEL } from "../components/ui/section-label";

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft";

export default function TeachingAssistantsPage() {
  usePageTitle("Manage My Assistants");
  const { showToast } = useToast();
  const { data: assistants, isPending, isError, refetch } = useMyAssistants();
  const { user: actor } = useAuth();
  const addAssistant = useAddTeachingAssistant();
  const removeFromTeam = useUnlinkSupervisor();
  const resendInvite = useResendInvite();

  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<AppUser | null>(null);

  const typo = useEmailTypoGuard(email, setEmail);

  async function onAdd() {
    if (!typo.check()) return;
    setError(null);
    setEmailError(null);
    const typed = email.trim();
    try {
      await addAssistant.mutateAsync(typed);
      setEmail("");
      // One message for created, linked and already-there: the server does not
      // say which, so neither can we ([0.21.0]).
      showToast(
        `${typed} is on your team. New accounts get an email to set a password.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setEmailError(err.message);
        return;
      }
      setError(
        err instanceof Error ? err.message : "Could not add the account.",
      );
    }
  }

  async function onResendInvite(target: AppUser) {
    try {
      await resendInvite.mutateAsync(target.id);
      showToast(`Invite resent to ${target.email}.`);
    } catch {
      showToast(`Couldn't resend the invite to ${target.email}. Try again.`, {
        tone: "error",
      });
    }
  }

  async function onConfirmRemove() {
    if (!confirmRemove) return;
    const target = confirmRemove;
    setPending(target.id);
    try {
      await removeFromTeam.mutateAsync({
        taId: target.id,
        instructorId: actor!.id,
      });
      showToast(`${displayName(target)} removed from your team.`);
      setConfirmRemove(null);
    } catch (err) {
      const reason = err instanceof Error ? err.message : "Try again.";
      showToast(`Couldn't remove ${displayName(target)}. ${reason}`, {
        tone: "error",
      });
      setConfirmRemove(null);
    } finally {
      setPending(null);
    }
  }

  const list = assistants ?? [];

  const columns: DataTableColumn<AppUser>[] = [
    {
      id: "name",
      header: "Name",
      width: "minmax(0,1.2fr)",
      cell: (ta) => (
        <span
          className={`min-w-0 max-w-[11rem] truncate text-sm font-medium text-foreground ${ta.status === "active" ? "" : "opacity-70"}`}
        >
          {displayName(ta)}
        </span>
      ),
    },
    {
      id: "email",
      header: "Email",
      width: "minmax(0,1.5fr)",
      cell: (ta) => (
        <span
          title={ta.email}
          className={`min-w-0 max-w-[13rem] truncate font-mono text-xs text-muted-foreground ${ta.status === "active" ? "" : "opacity-70"}`}
        >
          {ta.email}
        </span>
      ),
    },
    {
      id: "addedOn",
      header: "Added",
      width: "minmax(0,0.9fr)",
      hideWhenCompact: true,
      cell: (ta) => (
        <span className="truncate text-[13px] text-muted-foreground">
          {fmtDateOnly(ta.createdAt)}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      width: TABLE_STATUS_COLUMN_WIDTH,
      cell: (ta) => <UserStatusChip user={ta} />,
    },
    {
      id: "actions",
      header: "Actions",
      width: TABLE_ACTIONS_LABELLED_COLUMN_WIDTH,
      align: "right",
      cell: (ta) => (
        <span className="flex items-center justify-end gap-1">
          <RowAction
            onClick={() => setConfirmRemove(ta)}
            disabled={pending === ta.id}
          >
            Remove from team
          </RowAction>
          {/* Deactivation is root_admin's now ([0.21.0]), so the menu only
              exists for a pending invite. */}
          {isPendingInvite(ta) && (
            <RowActionMenu
              items={[
                {
                  label: "Resend invite",
                  onClick: () => void onResendInvite(ta),
                  disabled: resendInvite.isPending,
                },
              ]}
              ariaLabel={`More actions for ${displayName(ta)}`}
              disabled={pending === ta.id}
            />
          )}
        </span>
      ),
    },
  ];

  return (
    <Page>
      <PageHeader
        title="Manage My Assistants"
        subtitle="Accounts you supervise."
      />

      <section className="mt-8 shrink-0 rounded-xl bg-surface p-7 shadow-md">
        <p className={SECTION_LABEL}>Add teaching assistant</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onAdd();
          }}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">SMU email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailError(null);
              }}
              placeholder="name@smu.edu.sg"
              aria-invalid={emailError ? true : undefined}
              aria-describedby={
                emailError
                  ? "add-email-error"
                  : typo.suggestion
                    ? "add-email-hint"
                    : undefined
              }
              className={`w-64 ${FIELD}`}
            />
          </label>
          <Button
            type="submit"
            disabled={!email.trim() || addAssistant.isPending}
          >
            {addAssistant.isPending ? "Adding…" : "Add teaching assistant"}
          </Button>
          {(typo.suggestion || emailError) && (
            <div className="flex basis-full flex-col gap-1.5">
              <EmailTypoHint
                suggestion={typo.suggestion}
                onUse={typo.applySuggestion}
                onKeep={typo.keepAsTyped}
              />
              {emailError && (
                <FormNotice tone="error" id="add-email-error" role="alert">
                  {emailError}
                </FormNotice>
              )}
            </div>
          )}
        </form>

        {error && (
          <p
            className="mt-4 rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger"
            role="alert"
          >
            {error}
          </p>
        )}
      </section>

      {isError ? (
        <ErrorState
          className="mt-6"
          title="Could not load your list"
          description="Something went wrong reaching the server. Nothing has changed."
          onRetry={() => void refetch()}
        />
      ) : (
        <PageFill className="mt-6">
          <DataTable<AppUser>
            fillHeight
            columns={columns}
            rows={list}
            getRowId={(ta) => ta.id}
            isLoading={isPending}
            loadingLabel="Loading teaching assistants…"
            emptyState={
              <div>
                <p className="text-lg font-medium text-foreground">
                  No teaching assistants yet
                </p>
                <p className="mx-auto mt-2 max-w-sm text-muted-foreground">
                  Add one above by email. They will be able to screen answers
                  for your courses.
                </p>
              </div>
            }
          />
        </PageFill>
      )}

      {confirmRemove && (
        <Modal
          title={`Remove ${displayName(confirmRemove)} from your team?`}
          busy={removeFromTeam.isPending}
          onClose={() => setConfirmRemove(null)}
          footer={
            <>
              <Button
                variant="secondary"
                onClick={() => setConfirmRemove(null)}
                disabled={removeFromTeam.isPending}
              >
                Cancel
              </Button>
              <Button
                onClick={() => void onConfirmRemove()}
                disabled={removeFromTeam.isPending}
              >
                {removeFromTeam.isPending ? "Removing…" : "Remove from team"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-muted-foreground">
            They leave your team. Their account stays active, and anyone else
            who supervises them keeps them. If you were their only instructor,
            they can't screen answers until someone adds them again.
          </p>
        </Modal>
      )}
    </Page>
  );
}
