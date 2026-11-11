import { ArrowRight, RefreshCw } from 'lucide-react'

import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { api } from '@/lib/api'
import { navigate, withParams } from '@/lib/router'
import { useQuery } from '@/modules/client'

import { ScoreBadge } from '../compare/bits'

export default function CasesPage() {
  const cases = useQuery('cases', api.cases)
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Review"
        title="Cases"
        description="Each test case has one official answer (stored locally, never committed) and is re-run on our model when you open it."
        actions={
          <Button variant="outline" size="sm" onClick={() => void cases.refresh()} disabled={cases.fetching}>
            <RefreshCw className={cases.fetching ? 'animate-spin' : undefined} />
            Refresh
          </Button>
        }
      />
      {cases.error && <Card className="p-4 text-sm text-destructive">{cases.error.message}</Card>}
      <Card className="gap-0 overflow-hidden py-0">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs tracking-wide text-muted-foreground uppercase">
            <tr>
              <th className="px-4 py-3 font-medium">Case</th>
              <th className="px-4 py-3 font-medium">Trip</th>
              <th className="px-4 py-3 font-medium">Departure</th>
              <th className="px-4 py-3 font-medium">Official</th>
              <th className="px-4 py-3 font-medium">Score</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {cases.data?.map((c) => (
              <tr
                key={c.id}
                className="cursor-pointer border-t transition-colors hover:bg-muted/40"
                onClick={() => navigate(withParams('/compare', { case: c.id }))}
              >
                <td className="px-4 py-3 font-medium">{c.id}</td>
                <td className="px-4 py-3">
                  <div className="truncate">{c.origin}</div>
                  <div className="truncate text-muted-foreground">to {c.destination}</div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap">{c.departure}</td>
                <td className="px-4 py-3">
                  {c.has_truth ? (
                    <Badge variant="success" title={c.truth_files.join('\n')}>
                      stored ({c.truth_files.length})
                    </Badge>
                  ) : (
                    <Badge variant="warning" title={`opennav case run ${c.id}`}>
                      missing
                    </Badge>
                  )}
                </td>
                <td className="px-4 py-3">
                  {c.scores.opennav != null ? (
                    <ScoreBadge total={c.scores.opennav} />
                  ) : (
                    <span className="text-muted-foreground">not run yet</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <ArrowRight className="ml-auto size-4 text-muted-foreground" />
                </td>
              </tr>
            ))}
            {cases.data?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  No cases yet. Add cases/&lt;id&gt;.json to the repo.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
