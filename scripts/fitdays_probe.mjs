import { FitDaysApiError } from 'fitdays-api'

import {
  fetchFitdaysSync,
  formatLocalTimestamp,
  readFitdaysConfig,
  selectActiveMeasurements,
} from './fitdays_client.mjs'

const DISPLAY_LIMIT = 5

function optionalNumber(value, decimalPlaces = 2) {
  if (!Number.isFinite(value)) return null
  const factor = 10 ** decimalPlaces
  return Math.round((value + Number.EPSILON) * factor) / factor
}

function summarizeMeasurement(record) {
  return {
    measured_at_local: formatLocalTimestamp(record.measured_time),
    measured_at_utc: new Date(record.measured_time * 1000).toISOString(),
    weight_kg: optionalNumber(record.weight_kg),
    body_fat_pct: optionalNumber(record.bfr),
    bone_mass_kg: optionalNumber(record.bm),
    body_water_pct: optionalNumber(record.vwc),
    muscle_pct: optionalNumber(record.rom),
    skeletal_muscle_pct: optionalNumber(record.rosm),
    subcutaneous_fat_pct: optionalNumber(record.sfr),
    visceral_fat_level: optionalNumber(record.uvi),
    protein_pct: optionalNumber(record.pp),
    bmi: optionalNumber(record.bmi),
    bmr_kcal: optionalNumber(record.bmr, 0),
    body_age_years: optionalNumber(record.bodyage, 0),
    heart_rate_bpm: optionalNumber(record.hr, 0),
    impedance_adc: optionalNumber(record.adc, 0),
    weight_only: record.ext_data?.onlyMeasureWeight ?? null,
  }
}

function summarizeDevice(device) {
  return {
    firmware_version: device.firmware_ver,
    hardware_version: device.hardware_ver,
    model: device.model,
    name: device.name,
  }
}

async function main() {
  const config = readFitdaysConfig()
  const { client, sync } = await fetchFitdaysSync(config)
  const activeUserId = sync.data.account.active_suid
  const measurements = selectActiveMeasurements(sync.data).reverse()

  const summary = {
    active_profile_found: sync.data.users.some(
      (user) => user.suid === activeUserId && user.is_deleted === 0,
    ),
    device_count: sync.data.devices.length,
    devices: sync.data.devices.map(summarizeDevice),
    measurement_count: measurements.length,
    latest_measurements: measurements
      .slice(0, DISPLAY_LIMIT)
      .map(summarizeMeasurement),
    region_requested: config.region,
    resolved_api_host: new URL(client.baseUrl).host,
  }

  console.log(JSON.stringify(summary, null, 2))

  if (measurements.length === 0) {
    throw new Error('Fitdays returned no active, non-deleted measurements.')
  }
}

main().catch((error) => {
  if (error instanceof FitDaysApiError) {
    console.error(`Fitdays API error (${error.code}): ${error.message}`)
  } else if (error instanceof Error) {
    console.error(error.message)
  } else {
    console.error('Unknown error while running the Fitdays probe.')
  }
  process.exitCode = 1
})
