/**
 * Tests for WizardActionBar — the shared Back/Next navigation bar used at the
 * top and bottom of every wizard step and the OpenTag commit flow.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'
import { WizardActionBar } from './WizardActionBar'

describe('WizardActionBar', () => {
  it('renders Back and Next buttons with default labels', () => {
    render(<WizardActionBar onBack={vi.fn()} onNext={vi.fn()} />)
    expect(screen.getByRole('button', { name: /← Back/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Next →/i })).toBeInTheDocument()
  })

  it('calls onBack when Back is clicked', () => {
    const onBack = vi.fn()
    render(<WizardActionBar onBack={onBack} onNext={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /← Back/i }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('calls onNext when Next is clicked', () => {
    const onNext = vi.fn()
    render(<WizardActionBar onBack={vi.fn()} onNext={onNext} />)
    fireEvent.click(screen.getByRole('button', { name: /Next →/i }))
    expect(onNext).toHaveBeenCalledTimes(1)
  })

  it('renders custom backLabel and nextLabel', () => {
    render(
      <WizardActionBar
        onBack={vi.fn()}
        backLabel="← Previous"
        onNext={vi.fn()}
        nextLabel="Save & Next →"
      />,
    )
    expect(screen.getByRole('button', { name: /← Previous/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save & Next →/i })).toBeInTheDocument()
  })

  it('disables Next button when nextDisabled is true', () => {
    render(<WizardActionBar onBack={vi.fn()} onNext={vi.fn()} nextDisabled />)
    expect(screen.getByRole('button', { name: /Next →/i })).toBeDisabled()
  })

  it('shows busyLabel and disables Next when busy', () => {
    render(
      <WizardActionBar
        onBack={vi.fn()}
        onNext={vi.fn()}
        nextLabel="Save & Next →"
        busy
        busyLabel="Saving…"
      />,
    )
    expect(screen.getByRole('button', { name: /Saving…/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Saving…/i })).toBeDisabled()
    // The non-busy label should not be visible
    expect(screen.queryByRole('button', { name: /Save & Next →/i })).not.toBeInTheDocument()
  })

  it('renders extra slot content between Back and Next', () => {
    render(
      <WizardActionBar
        onBack={vi.fn()}
        onNext={vi.fn()}
        extra={<button>↻ Rescan</button>}
      />,
    )
    expect(screen.getByRole('button', { name: /↻ Rescan/i })).toBeInTheDocument()
  })

  it('renders only the right-side area when onBack is omitted', () => {
    render(<WizardActionBar onNext={vi.fn()} nextLabel="Next →" />)
    expect(screen.queryByRole('button', { name: /← Back/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Next →/i })).toBeInTheDocument()
  })

  it('renders only the left-side area when onNext is omitted (extra only on right)', () => {
    render(
      <WizardActionBar
        onBack={vi.fn()}
        extra={<button>Execute sync</button>}
      />,
    )
    expect(screen.getByRole('button', { name: /← Back/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Execute sync/i })).toBeInTheDocument()
  })

  it('disables Back when busy', () => {
    render(<WizardActionBar onBack={vi.fn()} onNext={vi.fn()} busy />)
    expect(screen.getByRole('button', { name: /← Back/i })).toBeDisabled()
  })
})
