/**
 * Tests for Step3Matches.buildSaveDecisions — the match-decision assembly.
 *
 * Regression: unmatched Spoolman rows render checked-by-default ('create') but the
 * component only writes a decision to state on an explicit toggle. The save path must
 * still persist a 'create' for those untouched rows, otherwise the planner sees
 * "no decision" and imports NOTHING into Filament DB (the reported "use existing
 * master adds nothing" bug — the variants never get a create decision).
 */

import { describe, it, expect, vi } from 'vitest'

// Mock the module's heavy imports so importing the pure helper is cheap and side-effect free.
vi.mock('../../api/client', () => ({ getWizardMatches: vi.fn(), postWizardMatches: vi.fn() }))
vi.mock('../../api/hooks', () => ({ useApi: vi.fn() }))
vi.mock('../../components/DeepLinks', () => ({ DeepLinks: () => null }))
vi.mock('../../components/HelpTip', () => ({ HelpTip: () => null }))
vi.mock('../../components/WizardActionBar', () => ({ WizardActionBar: () => null }))

import { buildSaveDecisions } from './Step3Matches'
import type {
  FilamentRef,
  MatchDecision,
  WizardMatchesResponse,
} from '../../api/types'

function ref(overrides: Partial<FilamentRef>): FilamentRef {
  return {
    spoolman_filament_id: null,
    filamentdb_filament_id: null,
    name: null,
    vendor: null,
    color: null,
    ...overrides,
  }
}

function makeData(overrides?: Partial<WizardMatchesResponse>): WizardMatchesResponse {
  return {
    matched: [],
    unmatched_spoolman: [],
    unmatched_filamentdb: [],
    ambiguous: [],
    saved_decisions: [],
    ...overrides,
  }
}

describe('buildSaveDecisions', () => {
  it('defaults an UNTOUCHED unmatched Spoolman row to action "create"', () => {
    const data = makeData({
      unmatched_spoolman: [ref({ spoolman_filament_id: 42, name: 'ELEGOO PLA Beige' })],
    })
    const out = buildSaveDecisions(data, {}) // no per-row toggles
    expect(out).toEqual([{ spoolman_filament_id: 42, action: 'create' }])
  })

  it('honors an explicit skip on an unmatched row (user unchecked it)', () => {
    const data = makeData({
      unmatched_spoolman: [ref({ spoolman_filament_id: 42 })],
    })
    const decisions: Record<number, MatchDecision> = {
      42: { spoolman_filament_id: 42, action: 'skip' },
    }
    const out = buildSaveDecisions(data, decisions)
    expect(out).toEqual([{ spoolman_filament_id: 42, action: 'skip' }])
  })

  it('persists multiple untouched new colors as creates (the "attach to existing master" case)', () => {
    const data = makeData({
      unmatched_spoolman: [
        ref({ spoolman_filament_id: 1, name: 'ELEGOO PLA Red' }),
        ref({ spoolman_filament_id: 2, name: 'ELEGOO PLA Blue' }),
        ref({ spoolman_filament_id: 3, name: 'ELEGOO PLA Green' }),
      ],
    })
    const out = buildSaveDecisions(data, {})
    expect(out).toEqual([
      { spoolman_filament_id: 1, action: 'create' },
      { spoolman_filament_id: 2, action: 'create' },
      { spoolman_filament_id: 3, action: 'create' },
    ])
  })

  it('defaults an untouched matched row to "link" with its FDB id', () => {
    const data = makeData({
      matched: [
        {
          spoolman: ref({ spoolman_filament_id: 7 }),
          filamentdb: ref({ filamentdb_filament_id: 'abc123' }),
          confidence: 1,
          vendor_dedup_hint: null,
        },
      ],
    })
    const out = buildSaveDecisions(data, {})
    expect(out).toEqual([
      { spoolman_filament_id: 7, action: 'link', filamentdb_id: 'abc123' },
    ])
  })

  it('omits an untouched ambiguous row (no safe default) but keeps an explicit pick', () => {
    const data = makeData({
      ambiguous: [
        { spoolman: ref({ spoolman_filament_id: 8 }), candidates: [] },
        { spoolman: ref({ spoolman_filament_id: 9 }), candidates: [] },
      ],
    })
    const decisions: Record<number, MatchDecision> = {
      9: { spoolman_filament_id: 9, action: 'link', filamentdb_id: 'pick9' },
    }
    const out = buildSaveDecisions(data, decisions)
    // #8 untouched → dropped; #9 explicit → kept
    expect(out).toEqual([
      { spoolman_filament_id: 9, action: 'link', filamentdb_id: 'pick9' },
    ])
  })
})
