import { PageHeader } from '@/components/layout/PageHeader'
import { AppearanceCard } from '@/components/theme/ThemePicker'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useHealth } from '@/modules/client'

export default function SettingsPage() {
  const health = useHealth()
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" description="Appearance and where the viewer reads its data." />
      <Card>
        <CardHeader>
          <CardTitle>Data</CardTitle>
          <CardDescription>
            Ground truth and road graphs are read from the local data folder and never leave this machine. Set
            OPENNAV_DATA_DIR before `opennav serve` to use another folder.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          {health.error ? (
            <span className="text-destructive">{health.error.message}</span>
          ) : (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
              <dt className="text-muted-foreground">Data folder</dt>
              <dd className="font-mono break-all">{health.data?.data_dir ?? '…'}</dd>
              <dt className="text-muted-foreground">Models</dt>
              <dd>{health.data?.models.join(', ') ?? '…'}</dd>
            </dl>
          )}
        </CardContent>
      </Card>
      <AppearanceCard />
    </div>
  )
}
