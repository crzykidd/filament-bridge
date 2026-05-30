import { useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import type { WizardTareOverride } from '../../api/types'
import Step1Connectivity from './Step1Connectivity'
import Step2Direction from './Step2Direction'
import Step3Matches from './Step3Matches'
import Step4Weights from './Step4Weights'
import Step5Variants from './Step5Variants'
import Step6Execute from './Step6Execute'

const STEPS = [
  { path: 'connectivity', label: 'Connectivity' },
  { path: 'direction', label: 'Direction' },
  { path: 'matches', label: 'Matches' },
  { path: 'weights', label: 'Weights' },
  { path: 'variants', label: 'Variants' },
  { path: 'execute', label: 'Execute' },
]

function Stepper({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((s, i) => (
        <div key={s.path} className="flex items-center">
          <div className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold border-2 ${
            i < current
              ? 'bg-indigo-600 border-indigo-600 text-white'
              : i === current
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-gray-300 text-gray-400 bg-white'
          }`}>
            {i + 1}
          </div>
          <span className={`ml-2 text-sm ${i === current ? 'text-indigo-600 font-medium' : 'text-gray-400'}`}>
            {s.label}
          </span>
          {i < STEPS.length - 1 && (
            <div className={`mx-3 h-0.5 w-8 ${i < current ? 'bg-indigo-600' : 'bg-gray-200'}`} />
          )}
        </div>
      ))}
    </div>
  )
}

export function WizardShell() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [tareOverrides, setTareOverrides] = useState<WizardTareOverride[]>([])

  function goTo(idx: number) {
    setStep(idx)
    navigate(`/wizard/${STEPS[idx].path}`)
  }

  function next() { if (step < STEPS.length - 1) goTo(step + 1) }
  function prev() { if (step > 0) goTo(step - 1) }

  const ctx = { next, prev, goTo, step, tareOverrides, setTareOverrides }

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Initial Sync Wizard</h1>
      <Stepper current={step} />
      <Routes>
        <Route index element={<Navigate to="connectivity" replace />} />
        <Route path="connectivity" element={<Step1Connectivity {...ctx} />} />
        <Route path="direction" element={<Step2Direction {...ctx} />} />
        <Route path="matches" element={<Step3Matches {...ctx} />} />
        <Route path="weights" element={<Step4Weights {...ctx} />} />
        <Route path="variants" element={<Step5Variants {...ctx} />} />
        <Route path="execute" element={<Step6Execute {...ctx} />} />
      </Routes>
    </div>
  )
}

export type WizardCtx = {
  next: () => void
  prev: () => void
  goTo: (idx: number) => void
  step: number
  tareOverrides: WizardTareOverride[]
  setTareOverrides: (o: WizardTareOverride[]) => void
}
