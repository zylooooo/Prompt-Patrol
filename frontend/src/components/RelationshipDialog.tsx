import { useMemo, useState } from 'react'
import Modal, { DialogButton } from './Modal'
import RowAction from './RowAction'
import { assistantsOf, linkedAt, supervisorsOf } from '../lib/api'
import { useLinkSupervision, useUnlinkSupervision } from '../lib/hooks'
import { useToast } from '../lib/toastContext'
import { displayName, isActive, type AppUser } from '../lib/types'

type Direction = 'supervisors' | 'assistants'

interface RelationshipDialogProps {
  subject: AppUser
  direction: Direction
  allUsers: AppUser[]
  onClose: () => void
}

function sinceText(iso: string | undefined): string {
  if (!iso) return 'Just now'
  return `Since ${new Date(iso).toLocaleDateString('en-SG', { month: 'short', year: 'numeric' })}`
}

// One dialog, two directions. A supervision link is the same row seen from
// either side, so the editing logic is shared and only the labels differ
export default function RelationshipDialog({
  subject,
  direction,
  allUsers,
  onClose,
}: RelationshipDialogProps) {
  const { showToast } = useToast()
  const link = useLinkSupervision()
  const unlink = useUnlinkSupervision()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isSupervisors = direction === 'supervisors'

  const original = useMemo(
    () => (isSupervisors ? supervisorsOf(subject.id) : assistantsOf(subject.id)).map((u) => u.id),
    [subject.id, isSupervisors],
  )
  const [selected, setSelected] = useState<string[]>(original)

  // a deactivated account cannot take on new work, so it is not offered
  const candidates = useMemo(
    () =>
      allUsers.filter(
        (u) =>
          isActive(u) &&
          (isSupervisors ? u.role === 'instructor' : u.role === 'teaching_assistant'),
      ),
    [allUsers, isSupervisors],
  )
  const byId = (id: string) => allUsers.find((u) => u.id === id)

  const available = candidates.filter(
    (candidate) => !selected.includes(candidate.id) && candidate.id !== subject.id,
  )
  const [toAdd, setToAdd] = useState('')

  // who else supervises this person, so sharing is visible before removing them
  function alsoWith(taId: string): string | null {
    if (isSupervisors) return null
    const others = supervisorsOf(taId).filter((supervisor) => supervisor.id !== subject.id)
    return others.length === 0 ? null : `Also with ${others.map(displayName).join(', ')}`
  }

  async function onSave() {
    setError(null)
    setSaving(true)
    try {
      const added = selected.filter((id) => !original.includes(id))
      const removed = original.filter((id) => !selected.includes(id))
      for (const id of added) {
        const pair = isSupervisors
          ? { instructorId: id, taId: subject.id }
          : { instructorId: subject.id, taId: id }
        await link.mutateAsync(pair)
      }
      for (const id of removed) {
        const pair = isSupervisors
          ? { instructorId: id, taId: subject.id }
          : { instructorId: subject.id, taId: id }
        await unlink.mutateAsync(pair)
      }
      showToast(
        isSupervisors
          ? `Supervisors updated for ${displayName(subject)}`
          : `Teaching assistants updated for ${displayName(subject)}`,
      )
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the changes.')
    } finally {
      setSaving(false)
    }
  }

  const dirty = selected.length !== original.length || selected.some((id) => !original.includes(id))

  return (
    <Modal
      title={
        isSupervisors
          ? `Supervisors for ${displayName(subject)}`
          : `Teaching assistants for ${displayName(subject)}`
      }
      subtitle={subject.email}
      onClose={onClose}
      busy={saving}
      footer={
        <>
          <DialogButton onClick={onClose} disabled={saving}>
            Cancel
          </DialogButton>
          <DialogButton onClick={() => void onSave()} variant="primary" disabled={!dirty || saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </DialogButton>
        </>
      }
    >
      <p className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">Current</p>

      <div className="mt-2.5 overflow-hidden rounded-lg border border-line bg-field">
        {selected.length === 0 && (
          <p className="px-4 py-4 text-sm text-ink-faint">
            {isSupervisors ? 'Nobody supervises this account yet.' : 'No teaching assistants yet.'}
          </p>
        )}
        {selected.map((id, i) => {
          const person = byId(id)
          const shared = alsoWith(id)
          const since = isSupervisors ? linkedAt(id, subject.id) : linkedAt(subject.id, id)
          return (
            <div
              key={id}
              className={`flex items-center justify-between gap-4 px-4 py-3 ${
                i < selected.length - 1 ? 'border-b border-line' : ''
              }`}
            >
              <div>
                <p className="text-sm font-medium text-ink">
                  {person ? displayName(person) : 'Unknown account'}
                </p>
                <p className="mt-0.5 text-xs text-ink-faint">
                  {shared ?? (original.includes(id) ? sinceText(since) : 'Not saved yet')}
                </p>
              </div>
              <RowAction
                onClick={() => setSelected(selected.filter((selectedId) => selectedId !== id))}
                disabled={saving}
              >
                Remove
              </RowAction>
            </div>
          )
        })}
      </div>

      <p className="mt-5 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
        {isSupervisors ? 'Add an instructor' : 'Add a teaching assistant'}
      </p>
      <div className="mt-2.5 flex items-center gap-3">
        <select
          value={toAdd}
          onChange={(e) => setToAdd(e.target.value)}
          className={`h-11 flex-1 rounded-md border border-line bg-surface px-3 text-sm ${
            toAdd ? 'text-ink' : 'text-hint'
          }`}
        >
          <option value="">
            {isSupervisors ? 'choose an instructor' : 'choose a teaching assistant'}
          </option>
          {available.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {displayName(candidate)}
            </option>
          ))}
        </select>
        <DialogButton
          onClick={() => {
            if (!toAdd) return
            setSelected([...selected, toAdd])
            setToAdd('')
          }}
          disabled={!toAdd}
        >
          Add
        </DialogButton>
      </div>

      <p className="mt-4 text-xs leading-relaxed text-ink-faint">
        {isSupervisors
          ? 'Removing every instructor leaves this account unassigned. It stays active and can be assigned again next semester.'
          : 'Removing someone here only ends their work with this instructor. Their account stays active.'}
      </p>

      {error && (
        <p className="mt-4 rounded-md bg-error-bg px-4 py-3 text-[13px] text-error" role="alert">
          {error}
        </p>
      )}
    </Modal>
  )
}
