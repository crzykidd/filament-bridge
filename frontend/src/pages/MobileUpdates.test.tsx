/**
 * Tests for MobileUpdates — the spool lookup keypad toggle (#79).
 *
 * The lookup box defaults to the numeric keypad (inputMode="numeric") because
 * number lookups dominate on a phone, and a #/Abc toggle switches it to a full
 * text keyboard for name/vendor/color search. `type` stays "text" throughout.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'

vi.mock('../api/client', () => ({ getMappings: vi.fn() }))
vi.mock('../api/hooks', () => ({ useApi: vi.fn() }))
vi.mock('../components/MobileSpoolUpdate', () => ({
  MobileSpoolUpdate: () => <div>mock-spool-update</div>,
}))
vi.mock('../components/ColorDisplay', () => ({ ColorDisplay: () => <span>color</span> }))

import MobileUpdates from './MobileUpdates'
import { useApi } from '../api/hooks'

describe('MobileUpdates lookup keypad (#79)', () => {
  it('defaults to the numeric keypad and toggles between numeric and text', () => {
    vi.mocked(useApi).mockReturnValue({ data: [], loading: false, error: null } as never)
    render(<MobileUpdates />)

    // Numeric by default (type stays text so the filter still matches names/numbers).
    const numeric = screen.getByPlaceholderText(/search by #/i) as HTMLInputElement
    expect(numeric.getAttribute('inputmode')).toBe('numeric')
    expect(numeric.getAttribute('type')).toBe('text')

    // Toggle → full text keyboard.
    fireEvent.click(screen.getByRole('button', { name: /switch to text keyboard/i }))
    const text = screen.getByPlaceholderText(/name \/ vendor \/ color/i) as HTMLInputElement
    expect(text.getAttribute('inputmode')).toBe('text')

    // Toggle back → numeric.
    fireEvent.click(screen.getByRole('button', { name: /switch to number keypad/i }))
    expect(screen.getByPlaceholderText(/search by #/i).getAttribute('inputmode')).toBe('numeric')
  })
})
