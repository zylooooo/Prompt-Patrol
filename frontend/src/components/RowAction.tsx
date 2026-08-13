import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

// One style for every row action. Padding exists even at rest so the hover
// fill does not make anything jump. Shared with RowActionLink below
const ROW_ACTION_CLASS =
  'cursor-pointer rounded-md px-2.5 py-[5px] text-[13px] text-navy-800 transition-colors hover:bg-navy-100 focus-visible:bg-navy-100 disabled:pointer-events-none disabled:opacity-45'

interface RowActionProps {
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}

export default function RowAction({ onClick, disabled, children }: RowActionProps) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={ROW_ACTION_CLASS}>
      {children}
    </button>
  )
}

// Same look for actions that navigate instead of changing something. A real
// link, so middle click and open-in-new-tab work
export function RowActionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className={ROW_ACTION_CLASS}>
      {children}
    </Link>
  )
}
