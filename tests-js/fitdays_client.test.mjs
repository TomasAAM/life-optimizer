import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatLocalTimestamp,
  normalizeMeasurement,
  selectActiveMeasurements,
} from '../scripts/fitdays_client.mjs'

function measurement(overrides = {}) {
  return {
    bfr: 14.23,
    bm: 3.62,
    ext_data: { onlyMeasureWeight: 0 },
    is_deleted: 0,
    measured_time: 1789114993,
    suid: 7,
    vwc: 61.92,
    weight_kg: 84.35,
    ...overrides,
  }
}

test('converts an instant to the Santiago wall clock', () => {
  assert.equal(formatLocalTimestamp(1789114993), '2026-09-11T05:23:13')
})

test('keeps only live records belonging to the active profile', () => {
  const selected = selectActiveMeasurements({
    account: { active_suid: 7 },
    weight_list: [
      measurement({ measured_time: 200 }),
      measurement({ is_deleted: 1, measured_time: 300 }),
      measurement({ measured_time: 100, suid: 8 }),
      measurement({ measured_time: 100 }),
    ],
  })
  assert.deepEqual(selected.map((record) => record.measured_time), [100, 200])
})

test('maps percentages to the existing mass-based schema', () => {
  assert.deepEqual(normalizeMeasurement(measurement()), {
    measured_at_local: '2026-09-11T05:23:13',
    weight_kg: 84.35,
    body_fat_pct: 14.23,
    lean_mass_kg: 72.347,
    bone_mass_kg: 3.62,
    body_water_kg: 52.2295,
    source: 'fitdays-cloud',
  })
})

test('does not invent composition for a weight-only reading', () => {
  assert.deepEqual(
    normalizeMeasurement(
      measurement({ bfr: 0, bm: 0, ext_data: { onlyMeasureWeight: 1 }, vwc: 0 }),
    ),
    {
      measured_at_local: '2026-09-11T05:23:13',
      weight_kg: 84.35,
      body_fat_pct: null,
      lean_mass_kg: null,
      bone_mass_kg: null,
      body_water_kg: null,
      source: 'fitdays-cloud',
    },
  )
})
