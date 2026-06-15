import { useDeepLinkBases } from './DeepLinkContext'

interface DeepLinksProps {
  filamentdbFilamentId?: string | null
  spoolmanSpoolId?: number | null
  spoolmanFilamentId?: number | null
}

function ExternalLink({ href, label, color }: { href: string; label: string; color: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={label}
      className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold text-white ${color} hover:opacity-80 transition-opacity`}
    >
      {label[0]}
    </a>
  )
}

function DisabledLink({ label, color }: { label: string; color: string }) {
  return (
    <span
      title={`${label} — not linked`}
      className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold text-white opacity-30 ${color} cursor-not-allowed`}
    >
      {label[0]}
    </span>
  )
}

export function DeepLinks({ filamentdbFilamentId, spoolmanSpoolId, spoolmanFilamentId }: DeepLinksProps) {
  const { filamentdbUrl, spoolmanUrl } = useDeepLinkBases()

  const fdbHref = filamentdbFilamentId && filamentdbUrl
    ? `${filamentdbUrl}/filaments/${filamentdbFilamentId}`
    : null

  const smSpoolHref = spoolmanSpoolId != null && spoolmanUrl
    ? `${spoolmanUrl}/spool/show/${spoolmanSpoolId}`
    : null

  const smFilamentHref = spoolmanFilamentId != null && spoolmanUrl
    ? `${spoolmanUrl}/filament/show/${spoolmanFilamentId}`
    : null

  return (
    <span className="flex items-center gap-1">
      {fdbHref
        ? <ExternalLink href={fdbHref} label="FDB" color="bg-blue-600" />
        : <DisabledLink label="FDB" color="bg-blue-600" />}
      {smSpoolHref
        ? <ExternalLink href={smSpoolHref} label="SM" color="bg-emerald-600" />
        : smFilamentHref
          ? <ExternalLink href={smFilamentHref} label="SM" color="bg-emerald-600" />
          : <DisabledLink label="SM" color="bg-emerald-600" />}
    </span>
  )
}
