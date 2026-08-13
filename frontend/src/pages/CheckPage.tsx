import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Tabs from '../components/Tabs'
import SingleCheckTab from '../components/SingleCheckTab'
import BatchTab from '../components/BatchTab'
import { hasScreeningAccess } from '../lib/api'
import { usePageTitle } from '../lib/usePageTitle'

type TabId = 'single' | 'batch'

export default function CheckPage() {
  usePageTitle('Check answers')
  const [tab, setTab] = useState<TabId>('single')

  // the api layer owns and enforces this rule, this just picks which view to show
  const unassigned = !hasScreeningAccess()

  return (
    <>
      <PageHeader
        title="Check answers"
        subtitle="Screen short answers for signs of AI generation."
        showModelStatus={!unassigned}
      />

      {unassigned ? (
        <section className="mt-8 rounded-xl border border-line bg-surface p-12 text-center">
          <p className="font-display text-lg font-medium text-ink">
            You are not assigned to an instructor yet
          </p>
          <p className="mx-auto mt-2 max-w-md text-sm text-ink-muted">
            Once an instructor adds you as their teaching assistant, you can screen answers for
            their courses. Ask them to add you, or contact your course administrator.
          </p>
        </section>
      ) : (
        <>
          <div className="mt-7">
            <Tabs
              tabs={[
                { id: 'single', label: 'Single answer' },
                { id: 'batch', label: 'Batch upload (CSV)' },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>
          <div className="mt-6" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {tab === 'single' ? <SingleCheckTab /> : <BatchTab />}
          </div>
        </>
      )}
    </>
  )
}
