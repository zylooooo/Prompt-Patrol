import { useState } from 'react'
import Modal, { DialogButton } from '../components/Modal'
import PageHeader from '../components/PageHeader'
import RowAction from '../components/RowAction'
import { findUserByEmail, linkedAt, lookupForLinking, supervisorsOf } from '../lib/api'
import { useAuth } from '../lib/authContext'
import {
  useCreateAccount,
  useLinkSupervision,
  useMyAssistants,
  useUnlinkSupervision,
} from '../lib/hooks'
import { fmtDateOnly } from '../lib/format'
import { usePageTitle } from '../lib/usePageTitle'
import { useToast } from '../lib/toastContext'
import { displayName, isActive, type AppUser } from '../lib/types'

export default function TeachingAssistantsPage() {
  usePageTitle('Teaching assistants')
  const { user: session } = useAuth()
  const { showToast } = useToast()
  const { data: assistants, isPending, isError, refetch } = useMyAssistants()
  const createAccount = useCreateAccount()
  const link = useLinkSupervision()
  const unlink = useUnlinkSupervision()

  // the session carries email and role only, so the full account comes from
  // the roster. Once GET /api/users/me exists this goes away
  const actor = session ? findUserByEmail(session.email) : undefined

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [existing, setExisting] = useState<AppUser | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<AppUser | null>(null)

  // other instructors supervising this person, so sharing is visible before acting
  function alsoWith(ta: AppUser): string {
    const others = supervisorsOf(ta.id).filter((supervisor) => supervisor.id !== actor?.id)
    return others.length === 0 ? '·' : others.map(displayName).join(', ')
  }

  // when they joined this list, which is the supervision link rather than the
  // account. A shared teaching assistant shows a different date to each
  // instructor, which is the point
  function addedOn(ta: AppUser): string {
    const iso = actor ? linkedAt(actor.id, ta.id) : undefined
    return iso ? fmtDateOnly(iso) : '·'
  }

  async function onAdd() {
    setError(null)
    // only ever asks whether this address can become my teaching assistant
    const lookup = lookupForLinking(email.trim())
    if (lookup.kind === 'linkable') {
      setExisting(lookup.user)
      return
    }
    if (lookup.kind === 'not-eligible') {
      setError('That email belongs to another kind of account. Ask your administrator for help.')
      return
    }
    try {
      const created = await createAccount.mutateAsync({
        name: name.trim() || undefined,
        email: email.trim(),
        role: 'teaching_assistant',
      })
      setName('')
      setEmail('')
      showToast(`${created.email} can now sign in with their SMU account`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add the account.')
    }
  }

  async function onConfirmLink() {
    if (!existing || !actor) return
    setError(null)
    try {
      await link.mutateAsync({ instructorId: actor.id, taId: existing.id })
      showToast(`${displayName(existing)} added to your teaching assistants`)
      setExisting(null)
      setName('')
      setEmail('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not link the account.')
      setExisting(null)
    }
  }

  async function onConfirmRemove() {
    if (!confirmRemove || !actor) return
    const target = confirmRemove
    setRowError(null)
    setPending(target.id)
    try {
      await unlink.mutateAsync({ instructorId: actor.id, taId: target.id })
      showToast(`${displayName(target)} removed from your teaching assistants`)
      setConfirmRemove(null)
    } catch (err) {
      setRowError({
        id: target.id,
        message: err instanceof Error ? err.message : 'Could not remove them.',
      })
      setConfirmRemove(null)
    } finally {
      setPending(null)
    }
  }

  const list = assistants ?? []

  return (
    <>
      <PageHeader
        title="Teaching assistants"
        subtitle="Accounts you supervise. They can screen answers for your courses."
        showModelStatus={false}
      />

      <section className="mt-8 rounded-xl border border-line bg-surface p-7">
        <p className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
          Add teaching assistant
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void onAdd()
          }}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-ink-muted">Name (optional)</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="full name"
              className="h-11 w-56 rounded-md border border-line bg-field px-3.5 text-sm text-ink placeholder:text-hint"
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-xs text-ink-muted">SMU email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@smu.edu.sg"
              className="h-11 w-64 rounded-md border border-line bg-field px-3.5 text-sm text-ink placeholder:text-hint"
            />
          </label>
          <button
            type="submit"
            disabled={!email.trim() || createAccount.isPending}
            className="h-11 rounded-lg bg-navy-800 px-5 text-sm font-semibold text-white transition-colors hover:bg-navy-700 disabled:opacity-50"
          >
            {createAccount.isPending ? 'Adding…' : 'Add teaching assistant'}
          </button>
        </form>

        <p className="mt-4 text-xs leading-relaxed text-ink-faint">
          There is no password to share. The email has to match their SMU account exactly, since
          that is what links the two together when they first sign in with Microsoft.
        </p>

        {error && (
          <p className="mt-4 rounded-md bg-error-bg px-4 py-3 text-[13px] text-error" role="alert">
            {error}
          </p>
        )}
      </section>

      {isPending ? (
        <section
          className="mt-6 flex flex-col gap-3 rounded-xl border border-line bg-surface p-7"
          aria-busy="true"
          aria-label="Loading teaching assistants"
        >
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-navy-50" />
          ))}
        </section>
      ) : isError ? (
        <section className="mt-6 rounded-xl border border-line bg-surface p-12 text-center" role="alert">
          <p className="font-display text-lg font-medium text-ink">Could not load your list</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-muted">
            Something went wrong reaching the server. Nothing has changed.
          </p>
          <button
            onClick={() => void refetch()}
            className="mt-5 h-11 rounded-lg border border-line px-5 text-sm text-ink-muted transition-colors hover:text-ink"
          >
            Try again
          </button>
        </section>
      ) : list.length === 0 ? (
        <section className="mt-6 rounded-xl border border-line bg-surface p-12 text-center">
          <p className="font-display text-lg font-medium text-ink">No teaching assistants yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-muted">
            Add one above. They will be able to screen answers for your courses.
          </p>
        </section>
      ) : (
        <section className="mt-6 rounded-xl border border-line bg-surface px-7 py-2">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  {['Name', 'Email', 'Also supervised by', 'Added', 'Status', ''].map((h) => (
                    <th
                      key={h}
                      className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.map((ta) => (
                  <tr key={ta.id} className="border-b border-line last:border-b-0">
                    <td className="py-4 pr-4 text-sm font-medium text-ink">{displayName(ta)}</td>
                    <td className="py-4 pr-4 font-mono text-xs text-ink-muted">{ta.email}</td>
                    <td className="py-4 pr-4 text-[13px] text-ink-muted">{alsoWith(ta)}</td>
                    <td className="py-4 pr-4 text-[13px] whitespace-nowrap text-ink-muted">
                      {addedOn(ta)}
                    </td>
                    <td className="py-4 pr-4">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                          isActive(ta) ? 'bg-human-bg text-human' : 'bg-unsure-bg text-unsure'
                        }`}
                      >
                        {isActive(ta) ? 'Active' : 'Deactivated'}
                      </span>
                    </td>
                    <td className="py-4 text-right whitespace-nowrap">
                      <RowAction onClick={() => setConfirmRemove(ta)} disabled={pending === ta.id}>
                        Remove
                      </RowAction>
                      {rowError?.id === ta.id && (
                        <p className="mt-1 text-xs text-error" role="alert">
                          {rowError.message}
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {existing && (
        <Modal
          title={`${displayName(existing)} already has an account`}
          subtitle={existing.email}
          busy={link.isPending}
          onClose={() => setExisting(null)}
          footer={
            <>
              <DialogButton onClick={() => setExisting(null)} disabled={link.isPending}>
                Cancel
              </DialogButton>
              <DialogButton
                onClick={() => void onConfirmLink()}
                variant="primary"
                disabled={link.isPending}
              >
                {link.isPending ? 'Adding…' : 'Add to my teaching assistants'}
              </DialogButton>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-ink-muted">
            Adding them links the existing account to you. No second account is created, and their
            work with other instructors is untouched.
          </p>
          <div className="mt-5 flex items-center justify-between gap-4 rounded-lg border border-line bg-field px-4 py-3.5">
            <p className="text-sm font-medium text-ink">{displayName(existing)}</p>
            <p className="text-[13px] text-ink-muted">
              {supervisorsOf(existing.id).length === 0
                ? 'Currently unassigned'
                : `Currently with ${supervisorsOf(existing.id).map(displayName).join(', ')}`}
            </p>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-ink-faint">
            The name on the account stays as it is. Only an administrator can rename it.
          </p>
        </Modal>
      )}

      {confirmRemove && (
        <Modal
          title={`Remove ${displayName(confirmRemove)}`}
          busy={unlink.isPending}
          onClose={() => setConfirmRemove(null)}
          footer={
            <>
              <DialogButton onClick={() => setConfirmRemove(null)} disabled={unlink.isPending}>
                Cancel
              </DialogButton>
              <DialogButton
                onClick={() => void onConfirmRemove()}
                variant="primary"
                disabled={unlink.isPending}
              >
                {unlink.isPending ? 'Removing…' : 'Remove'}
              </DialogButton>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-ink-muted">
            {supervisorsOf(confirmRemove.id).length > 1
              ? 'They keep their account and continue working with their other instructors.'
              : 'They keep their account. It becomes unassigned and stays active until someone adds them again.'}
          </p>
        </Modal>
      )}
    </>
  )
}
