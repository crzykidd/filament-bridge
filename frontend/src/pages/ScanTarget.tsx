/**
 * ScanTarget — the bare QR scan-target page (`/scan/:filId/:spoolId`).
 *
 * Rendered OUTSIDE the <Layout/> wrapper (no side nav): this is what a phone
 * opens after scanning the label QR (via the `/r/{fil}/{spool}` redirect). It is
 * a single-purpose, full-screen frame around the shared MobileSpoolUpdate card
 * (frame modeled on Login.tsx). If the feature is disabled the API 403s and the
 * card surfaces that message inline rather than crashing.
 */

import { useParams } from 'react-router-dom'
import { MobileSpoolUpdate } from '../components/MobileSpoolUpdate'

export default function ScanTarget() {
  const { filId, spoolId } = useParams<{ filId: string; spoolId: string }>()

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-start justify-center px-4 py-8">
      {filId && spoolId ? (
        <MobileSpoolUpdate filId={filId} spoolId={spoolId} />
      ) : (
        <p className="text-sm text-red-600 dark:text-red-400 mt-12">Invalid scan link.</p>
      )}
    </div>
  )
}
