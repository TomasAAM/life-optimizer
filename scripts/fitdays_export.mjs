import { FitDaysApiError } from 'fitdays-api'

import { fetchFitdaysRows, readFitdaysConfig } from './fitdays_client.mjs'

async function main() {
  const rows = await fetchFitdaysRows(readFitdaysConfig())
  console.log(JSON.stringify(rows))
}

main().catch((error) => {
  if (error instanceof FitDaysApiError) {
    console.error(`Fitdays API error (${error.code}): ${error.message}`)
  } else if (error instanceof Error) {
    console.error(error.message)
  } else {
    console.error('Unknown error while exporting Fitdays measurements.')
  }
  process.exitCode = 1
})
