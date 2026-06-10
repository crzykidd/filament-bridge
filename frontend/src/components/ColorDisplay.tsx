/**
 * ColorDisplay — multicolor-aware color swatch with optional label.
 *
 * - multicolor (2+ comma-separated hexes in multiColorHexes): CSS linear-gradient
 *   swatch + "Gradient" / "Coaxial" / "Multicolor" label based on direction.
 * - single (colorHex set): solid swatch + optional hex text.
 * - neither: neutral dash placeholder.
 */

interface ColorDisplayProps {
  colorHex?: string | null
  multiColorHexes?: string | null
  multiColorDirection?: string | null
  /** When true, render a text label next to the swatch */
  showLabel?: boolean
}

function normalizeHex(hex: string): string {
  const s = hex.trim()
  return s.startsWith('#') ? s : `#${s}`
}

function multicolorLabel(direction: string | null | undefined): string {
  if (direction === 'longitudinal') return 'Gradient'
  if (direction === 'coaxial') return 'Coaxial'
  return 'Multicolor'
}

export function ColorDisplay({
  colorHex,
  multiColorHexes,
  multiColorDirection,
  showLabel = false,
}: ColorDisplayProps) {
  const hexes = multiColorHexes
    ? multiColorHexes.split(',').map(h => h.trim()).filter(Boolean)
    : []

  if (hexes.length >= 2) {
    const normalized = hexes.map(normalizeHex)
    const gradient = `linear-gradient(to right, ${normalized.join(', ')})`
    const label = multicolorLabel(multiColorDirection)
    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-gray-600 shrink-0"
          style={{ background: gradient }}
          title={normalized.join(' / ')}
        />
        {showLabel && (
          <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
        )}
      </span>
    )
  }

  if (colorHex) {
    const hex = normalizeHex(colorHex)
    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-gray-600 shrink-0"
          style={{ backgroundColor: hex }}
          title={hex}
        />
        {showLabel && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
            {hex}
          </span>
        )}
      </span>
    )
  }

  return <span className="text-gray-400 dark:text-gray-500 text-sm">—</span>
}
