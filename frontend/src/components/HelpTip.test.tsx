/**
 * HelpTip render tests:
 *   - tooltip text is hidden initially
 *   - tooltip appears on focus
 *   - tooltip hides on Escape
 *   - learnMoreHref renders a "Learn more" link inside the tooltip
 */

import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'
import { HelpTip } from './HelpTip'

describe('HelpTip', () => {
  it('does not show tooltip initially', () => {
    render(<HelpTip text="Helpful text here" />)
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('shows tooltip on focus', () => {
    render(<HelpTip text="Helpful text here" />)
    const btn = screen.getByRole('button', { name: 'Help' })
    fireEvent.focus(btn)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Helpful text here')
  })

  it('hides tooltip on Escape', () => {
    render(<HelpTip text="Helpful text here" />)
    const btn = screen.getByRole('button', { name: 'Help' })
    fireEvent.focus(btn)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('renders a Learn more link when learnMoreHref is provided', () => {
    render(<HelpTip text="Some tip" learnMoreHref="/docs/sync-model" />)
    const btn = screen.getByRole('button', { name: 'Help' })
    fireEvent.focus(btn)
    const link = screen.getByRole('link', { name: /learn more/i })
    expect(link).toHaveAttribute('href', '/docs/sync-model')
  })
})
