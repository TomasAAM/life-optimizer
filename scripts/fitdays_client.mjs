import { FitDaysClient } from 'fitdays-api'

export const LOCAL_TIME_ZONE = 'America/Santiago'
export const VALID_REGIONS = new Set(['us', 'eu', 'cn'])

function roundNumber(value, decimalPlaces = 2) {
  if (!Number.isFinite(value)) return null
  const factor = 10 ** decimalPlaces
  return Math.round((value + Number.EPSILON) * factor) / factor
}

function hasComposition(record) {
  return String(record.ext_data?.onlyMeasureWeight ?? '0') !== '1'
    && Number.isFinite(record.bfr)
    && record.bfr > 0
}

/** Read and validate the Fitdays connection settings from the environment. */
export function readFitdaysConfig() {
  const email = process.env.FITDAYS_EMAIL?.trim()
  const password = process.env.FITDAYS_PASSWORD?.trim()
  const region = (process.env.FITDAYS_REGION ?? 'us').trim().toLowerCase()

  if (!email) {
    throw new Error('FITDAYS_EMAIL is required. Add it to the environment.')
  }
  if (!password) {
    throw new Error('FITDAYS_PASSWORD is required. Add it to the environment.')
  }
  if (!VALID_REGIONS.has(region)) {
    throw new Error('FITDAYS_REGION must be one of: us, eu, cn.')
  }

  return { email, password, region }
}

/** Convert Unix seconds to a timezone-naive Santiago wall-clock timestamp. */
export function formatLocalTimestamp(unixSeconds) {
  const date = new Date(unixSeconds * 1000)
  if (Number.isNaN(date.valueOf())) {
    throw new Error(`Invalid Fitdays measurement timestamp: ${unixSeconds}`)
  }
  const parts = new Intl.DateTimeFormat('en-CA', {
    day: '2-digit',
    hour: '2-digit',
    hour12: false,
    minute: '2-digit',
    month: '2-digit',
    second: '2-digit',
    timeZone: LOCAL_TIME_ZONE,
    year: 'numeric',
  }).formatToParts(date)
  const byType = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${byType.year}-${byType.month}-${byType.day}T${byType.hour}:${byType.minute}:${byType.second}`
}

/** Select the active profile's live measurements and sort them oldest first. */
export function selectActiveMeasurements(data) {
  const activeUserId = data.account.active_suid
  return data.weight_list
    .filter((record) => record.suid === activeUserId && record.is_deleted === 0)
    .sort((left, right) => left.measured_time - right.measured_time)
}

/** Convert one Fitdays record into the existing body_composition schema. */
export function normalizeMeasurement(record) {
  const weightKg = roundNumber(record.weight_kg, 4)
  if (weightKg === null || weightKg <= 0) {
    throw new Error('Fitdays returned a measurement without a valid weight.')
  }

  const compositionAvailable = hasComposition(record)
  const bodyFatPct = compositionAvailable ? roundNumber(record.bfr, 4) : null
  const bodyWaterPct = compositionAvailable ? roundNumber(record.vwc, 4) : null

  return {
    measured_at_local: formatLocalTimestamp(record.measured_time),
    weight_kg: weightKg,
    body_fat_pct: bodyFatPct,
    lean_mass_kg: bodyFatPct === null
      ? null
      : roundNumber(weightKg * (1 - bodyFatPct / 100), 4),
    bone_mass_kg: compositionAvailable ? roundNumber(record.bm, 4) : null,
    body_water_kg: bodyWaterPct === null
      ? null
      : roundNumber(weightKg * bodyWaterPct / 100, 4),
    source: 'fitdays-cloud',
  }
}

/** Authenticate, fetch the complete history, and return the SDK response. */
export async function fetchFitdaysSync({ email, password, region }) {
  const client = new FitDaysClient({ region })
  await client.login(email, password)
  const sync = await client.syncAll()
  return { client, sync }
}

/** Fetch and normalize every active, non-deleted Fitdays measurement. */
export async function fetchFitdaysRows(config) {
  const { sync } = await fetchFitdaysSync(config)
  return selectActiveMeasurements(sync.data).map(normalizeMeasurement)
}
