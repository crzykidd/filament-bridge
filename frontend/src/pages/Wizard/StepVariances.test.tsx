/**
 * Regression test for StepVariances — the SM→FDB Variances step.
 *
 * Guards against the TDZ crash shipped in v0.6.4: the `missingTareCount` useMemo
 * (added in #13) referenced `effectiveUngrouped` / `allFilamentData` in its factory
 * and dependency array but was declared ABOVE them, so it threw
 * "Cannot access 'effectiveUngrouped' before initialization" on every render of the
 * SM variances step (reached right after selecting brands in the Match step).
 *
 * tsc does NOT catch a TDZ — only an actual render does — so this smoke test is the
 * guard. There was no StepVariances test before, which is why the bug shipped.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../../api/hooks', () => ({
  useApi: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  getWizardVariances: vi.fn(),
  getWizardVariants: vi.fn(),
  getWizardWeights: vi.fn(),
  postWizardMatchSkip: vi.fn(),
  postWizardSmVariants: vi.fn(),
  postWizardVariants: vi.fn(),
}))

vi.mock('../../components/DeepLinks', () => ({
  DeepLinks: () => null,
}))

import { useApi } from '../../api/hooks'
import type { VariancesFilament, VariancesResponse } from '../../api/types'
import StepVariances from './StepVariances'

const CTX = {
  prev: vi.fn(),
  next: vi.fn(),
  goTo: vi.fn(),
  step: 4,
  tareOverrides: [],
  setTareOverrides: vi.fn(),
}

function fil(id: number, name: string, over?: Partial<VariancesFilament>): VariancesFilament {
  return {
    ref: { spoolman_filament_id: id, filamentdb_filament_id: null, name, vendor: 'ELEGOO', color: 'FF0000', material: 'PLA' },
    spool_ids: [id * 10],
    tare: null,
    tare_source: 'needs_input',
    is_master: false,
    conflicts: [],
    suggest_exclude: false,
    material: 'PLA',
    density: 1.24,
    spool_weight: null,
    settings_extruder_temp: null,
    settings_bed_temp: null,
    material_type: 'PLA',
    diameter: 1.75,
    color_hex: 'FF0000',
    ...over,
  }
}

function smData(): VariancesResponse {
  return {
    direction: 'spoolman',
    groups: [
      {
        base_name: 'ELEGOO PLA',
        vendor: 'ELEGOO',
        material: 'PLA',
        suggested_master: fil(2, 'ELEGOO PLA Blue').ref,
        members: [fil(2, 'ELEGOO PLA Blue', { is_master: true })],
        existing_fdb_parent: null,
      },
    ],
    ungrouped: [fil(1, 'ELEGOO PLA Red')],
  }
}

describe('StepVariances — SM variances step renders without TDZ (#14 regression)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the SM grouping/tare UI (would throw "before initialization" before the fix)', () => {
    vi.mocked(useApi).mockReturnValue({
      data: smData(),
      loading: false,
      error: null,
      reload: vi.fn(),
      refetch: vi.fn(),
    })
    // The render itself is the assertion: a TDZ in missingTareCount would throw here.
    render(<StepVariances {...CTX} />)
    expect(screen.getAllByText(/Save & Next/).length).toBeGreaterThan(0)
    // needs_input tare surfaces the required badge, proving the tare-gating path ran.
    expect(screen.getAllByText(/required/i).length).toBeGreaterThan(0)
  })

  it('renders fine when tares ARE set (250 g / 193 g) — the crash was never about missing tare', () => {
    // Mirrors the real report: spools selected with tare already set (mostly 250 g, one 193 g).
    const data: VariancesResponse = {
      direction: 'spoolman',
      groups: [
        {
          base_name: 'ELEGOO PLA',
          vendor: 'ELEGOO',
          material: 'PLA',
          suggested_master: fil(2, 'ELEGOO PLA Blue').ref,
          members: [fil(2, 'ELEGOO PLA Blue', { is_master: true, tare: 250, tare_source: 'spoolman', spool_weight: 250 })],
          existing_fdb_parent: null,
        },
      ],
      ungrouped: [
        fil(1, 'ELEGOO PLA Red', { tare: 250, tare_source: 'spoolman', spool_weight: 250 }),
        fil(3, 'ELEGOO PLA Black', { tare: 193, tare_source: 'spoolman', spool_weight: 193 }),
      ],
    }
    vi.mocked(useApi).mockReturnValue({ data, loading: false, error: null, reload: vi.fn(), refetch: vi.fn() })
    render(<StepVariances {...CTX} />)
    expect(screen.getAllByText(/Save & Next/).length).toBeGreaterThan(0)
  })

  it('issue #78: a group attaching to an existing FDB master with a known tare pre-fills from it, not "required"', () => {
    // Mirrors the bug report: "CC3D PLA (Master)" — Spoolman side has no spool_weight
    // (tare_source would be needs_input), but the group attaches to an existing FDB
    // master that already has a tare (#76 backfill) — the backend resolves it via
    // resolve_family_tare and returns tare_source: "filamentdb_master".
    const data: VariancesResponse = {
      direction: 'spoolman',
      groups: [
        {
          base_name: 'CC3D PLA',
          vendor: 'CC3D',
          material: 'PLA',
          suggested_master: fil(2, 'CC3D PLA Purple').ref,
          members: [
            fil(2, 'CC3D PLA Purple', { is_master: true, tare: 154, tare_source: 'filamentdb_master', spool_weight: null }),
          ],
          existing_fdb_parent: {
            spoolman_filament_id: null,
            filamentdb_filament_id: 'fdb-cc3d-pla',
            name: 'CC3D PLA (Master)',
            vendor: 'CC3D',
            color: null,
            material: 'PLA',
          },
        },
      ],
      ungrouped: [],
    }
    vi.mocked(useApi).mockReturnValue({ data, loading: false, error: null, reload: vi.fn(), refetch: vi.fn() })
    render(<StepVariances {...CTX} />)
    // Pre-filled from the family tare — no "required" badge anywhere.
    expect(screen.queryByText(/required/i)).not.toBeInTheDocument()
    // Distinct source label so the user knows the value came from the FDB master.
    expect(screen.getAllByText(/from the Filament DB master/i).length).toBeGreaterThan(0)
    // The tare input itself is pre-filled with the resolved family value.
    expect(screen.getByDisplayValue('154')).toBeInTheDocument()
  })
})
