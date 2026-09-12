# Automatic data retrieval from the Vitalia/Fitdays scale

**Research date:** 2026-09-11

**Scale context:** Vitalia by Linkon, Bluetooth, four-electrode/ITO model using the Fitdays Android app
**Goal:** move weigh-ins into the Life Optimizer Dashboard automatically, without manual CSV handling

## Recommendation

There are three credible automatic routes. The easiest route for this dashboard is **direct read-only access to the Fitdays cloud** through the unofficial `fitdays-api` SDK. It needs no additional phone app, account, file relay, inbound server, or hardware. The existing GitHub Actions job can fetch the same history that the Fitdays app displays and upsert it into Supabase. It also preserves the complete vendor record.

The tradeoff is that Fitdays does not document this consumer API. The integration could need repair if Fitdays changes its private app protocol. For a supported API and a smaller data set, use **Fitdays → Fitbit → Fitbit Web API → Supabase**. Fitdays documents that its Fitbit integration uploads after each completed measurement while the integration is enabled and the phone has network access.[^1] Fitbit's Web API provides authenticated endpoints for weight and body-fat logs, including date-range queries.[^2]

The third choice is **direct Bluetooth capture** with BLE Scale Sync. It removes Fitdays and the phone entirely, but requires a small always-on receiver near the scale and a compatibility test.

## Decision matrix

| Route | Automatic after setup | Keeps current scale | Phone requirement | Metrics | Stability | Extra hardware | Recommended use |
|---|---:|---:|---|---|---|---:|---|
| Fitdays cloud → unofficial SDK | Yes, after Fitdays receives the reading | Yes | Fitdays must receive/upload readings | Full vendor record | Medium-low; undocumented API | No | **Easiest; start with a read-only proof** |
| Fitdays → Fitbit → official API | Yes, after Fitdays receives the reading | Yes | Fitdays must receive/upload readings | Weight + body fat | Highest of the cloud routes | No | Supported fallback |
| Scale BLE → BLE Scale Sync → webhook | Yes; stepping on the scale is the only action | Yes, if protocol matches | No | Weight + impedance-derived metrics | Medium; open source and local | Pi/ESP32 or an always-on nearby PC | Best long-term independence |
| Scale BLE → openScale → openScale Sync → webhook | Near-real-time after openScale records a measurement | Yes, if protocol matches | Android phone nearby | Weight + supported body metrics | Medium | No | Good phone-only experiment |
| Fitdays → Health Connect → HC Webhook → Supabase | Scheduled/interval delivery | Yes | Android phone | Health Connect-supported metrics | Medium-high; open source | No | Better replacement for the sheet relay |
| Fitdays MCP server | Only when a client calls it or another scheduler wraps it | Yes | Fitdays must receive/upload readings | Full vendor record | Same risk as unofficial Fitdays SDK | No | Interactive queries, not ingestion |
| Official Fitdays data portability/API request | Unknown | Yes | Unknown | Potentially complete | Unknown | No | Ask Fitdays; not currently self-service |

## Option 1: read the Fitdays cloud directly

Fitdays confirms that it stores measurement history on its servers.[^6] Two recent open-source projects implement read-only access to the same private mobile API:

- `fitdays-api`, a TypeScript SDK with email/phone login, regional redirect handling, full-history sync, typed measurement records, and no runtime dependencies.[^7]
- `fitdays`, an async Python client that exposes weight, BMI, body fat, subcutaneous fat, visceral fat, muscle, skeletal muscle, bone mass, body water, protein, BMR, body age, heart rate, and impedance.[^8]

The TypeScript project is the better reference today: it has materially more development history, automated coverage thresholds, no runtime dependencies, and explicit parsing of Fitdays' `ext_data` measurement payload. It can run as a small Node step in the existing GitHub Actions workflow and emit normalized JSON for the Python ingestion layer.

### Strengths

- No extra account, phone exporter, sheet, webhook receiver, or local hardware.
- Retrieves the complete Fitdays record rather than the smaller subset supported by Health Connect or Fitbit.
- Can backfill years of history and filter deleted or other household users' records.
- Fits the current scheduled pull architecture.

### Risks

- Fitdays has no public consumer API. These clients reproduce the private app protocol, so endpoints, signing rules, or payloads can change without notice.[^7]
- Authentication uses a password-derived digest that is effectively equivalent to the Fitdays password for this API. It must be treated as a secret. Use a unique Fitdays password that is not reused anywhere else.[^8]
- The current SDKs are young, lightly adopted projects. Pin the exact version and add a clear failure alert.
- Email and phone login are implemented. A social-login-only account may need a normal Fitdays password before this works.
- This still depends on Fitdays receiving the Bluetooth measurement from the scale.

### How to reduce the risk

Run a read-only proof first using a dedicated Fitdays password. Verify the returned device, active user, timestamps, deleted-record behavior, and five known measurements before changing the production ingest. Keep the existing source adapter boundary so the dashboard can switch between Fitbit, Fitdays, Health Connect webhook, or a sheet without changing charts or the database contract.

## Option 2: Fitdays to Fitbit to the dashboard

### Data flow

```text
Vitalia scale
  → Fitdays app and Fitdays cloud
  → Fitdays' built-in Fitbit integration
  → Fitbit Web API
  → scheduled GitHub Actions ingestion
  → Supabase body_composition
  → dashboard Body tab
```

Fitdays' own FAQ describes the Fitbit authorization flow and says data uploads after completed measurements when the Fitbit switch remains enabled and the network is available.[^1] Fitbit documents OAuth-based access and read endpoints for body weight and body-fat logs.[^2] The log records include date and time, so the existing `measured_at_local` protocol check can remain intact.[^4]

### One-time setup

1. Create a Fitbit account; owning a Fitbit device is not required for the Web API.
2. In Fitdays, open **Account → Settings → Fitbit**, sign in, and grant access.
3. Complete one test weigh-in and confirm that Fitbit shows both weight and body fat.
4. Register a personal Fitbit API application and authorize the `weight` scope.
5. Store the Fitbit client ID, client secret, refresh token, and access token as GitHub repository secrets.
6. Add a scheduled reader that refreshes OAuth tokens, requests recent weight/fat logs, joins records by date/time, and upserts them into `body_composition`.

### Strengths

- The dashboard reads a documented API instead of a private mobile endpoint.
- No Android exporter, public Google Sheet, MCP service, Raspberry Pi, or inbound webhook is needed.
- A scheduled full lookback can remain idempotent and correct late-arriving records.
- The Fitdays password never enters the dashboard's secrets.

### Limits

- Fitdays must first receive the measurement. Its standard Bluetooth models generally sync live while the app is open, or upload stored offline readings the next time the app is opened within Bluetooth range.[^5]
- Only weight and body-fat percentage are documented as syncing to Fitbit.[^3]
- OAuth setup is more involved than entering one URL, and refresh tokens must be rotated and stored correctly.
- This path depends on two clouds: Fitdays and Fitbit.

## Option 3: capture the scale directly over Bluetooth

BLE Scale Sync is an open-source, always-on bridge for Bluetooth scales. It runs on Linux, macOS, Windows, Home Assistant, or through an ESP32 Bluetooth proxy. Once running, stepping on the scale is the only user action; no phone app is required.[^9] It supports 35 protocol adapters plus a standard Bluetooth SIG fallback, including MGB/Swan/Icomon/YG and several other ICOMON-related families.[^10]

Its generic webhook exporter can send JSON to a Supabase Edge Function with a custom secret header.[^11]

```text
Vitalia scale
  → Bluetooth
  → BLE Scale Sync on Pi/PC/ESP32 proxy
  → authenticated webhook
  → Supabase body_composition
  → dashboard Body tab
```

### Compatibility gate

The Vitalia retail name does not identify the Bluetooth protocol. Fitdays is used by many white-label scale families, and different units can advertise names such as `icomon`, `MY_SCALE`, or a model-specific identifier.[^12] Compatibility therefore needs one empirical scan while standing on the scale:

```text
ble-scale-sync scan
```

The zero-cost test is to run the standalone scanner on the existing Windows laptop with Bluetooth enabled. Docker Desktop on Windows cannot access the host BLE radio, so the test must use the standalone Node.js build.[^13] If the scanner identifies a supported adapter and returns impedance, the production receiver can be:

- a nearby Raspberry Pi Zero 2 W;
- an existing always-on PC or NAS with a BLE adapter; or
- a low-cost ESP32 proxy near the scale, relaying to a server elsewhere.

### Strengths

- Removes Fitdays, Health Connect, Fitbit, and the phone from the data path.
- Keeps data under local control until the configured webhook sends it to Supabase.
- Delivers readings within seconds and can also append a local CSV/JSONL safety copy.
- Unsupported protocols can be diagnosed from scan output and Bluetooth captures.

### Limits

- It requires an always-on Bluetooth receiver near the scale.
- Exact Vitalia compatibility is unknown until the scan is run.
- For scales that expose weight and impedance, the project calculates body composition with open formulas. These values can differ from Fitdays because Fitdays' vendor formula is proprietary. Weight is the direct sensor reading; the composition values are estimates.[^14]
- The project has no retry queue for failed cloud exports. Configure the local file exporter alongside the webhook so a network outage does not lose the raw reading.[^15]

## Option 4: replace Fitdays with openScale on Android

openScale supports many Bluetooth scales and includes an MGB/Swan/Icomon handler with body metrics.[^16] Its companion app, openScale Sync, can publish measurements in real time to a generic webhook, retry failed sends, and perform periodic background reconciliation.[^17]

This route removes the Fitdays cloud and needs no new hardware:

```text
Vitalia scale → openScale → openScale Sync → Supabase webhook
```

Test whether openScale recognizes the scale before considering this route. Compatibility is protocol-specific, and openScale's main interaction model may require opening or connecting from the app for some GATT scales. As with BLE Scale Sync, locally calculated body-composition values may differ from Fitdays.

## Option 5: Health Connect directly to a webhook

If keeping Health Connect is acceptable, the current public-sheet relay can be simplified. HC Webhook is an open-source Android app that reads 31 Health Connect data types on an interval or fixed schedule and posts JSON directly to one or more webhooks.[^18] It supports custom headers, incremental delivery, brief retries, and later scheduled retries.[^19]

```text
Fitdays → Health Connect → HC Webhook → Supabase Edge Function
```

This is a cleaner automatic Health Connect design than publishing a Google Sheet. It supports weight, body fat, lean body mass, bone mass, and basal metabolic rate among its 31 record types. It still depends on Android background execution and Fitdays writing records into Health Connect. Battery optimization must be disabled for dependable scheduling on aggressive Android builds.

HCGateway is another open-source Health Connect-to-REST project, but it introduces a server and database and describes itself as still in development. For this dashboard, HC Webhook's push model is simpler.[^20]

## Option 6: MCP

There is a Fitdays MCP server exposing `list_users`, `list_devices`, `get_weight_history`, `get_latest_weight`, and `refresh_sync` over the same unofficial Fitdays API.[^21] A Cloudflare Worker variant adds OAuth and stores the Fitdays credential in encrypted Worker KV.[^22]

MCP does not unlock a new data source. It wraps the same private Fitdays API so an AI client can ask questions interactively. A scheduled ingestion job would still need to invoke the MCP tool and persist its result, adding another service layer. The dashboard should call the underlying SDK directly. An MCP server is useful later if conversational access to the scale history is desired.

None of the currently available Codex plugins provides a direct Fitdays, Health Connect, or Vitalia connector. Google Drive would only help consume an exported file; it would not make the scale export automatically.

## Option 7: request Fitdays' official portability interface

Fitdays' current privacy policy says users can export CSV data, request batch extraction, authorize third-party sharing, and use data-migration tools or industry-standard API interfaces.[^23] No public developer documentation, endpoint, OAuth flow, or consumer self-service API could be found. The policy is framed around EU Data Act compliance, so availability for a Chilean account is uncertain.

It is still worth sending one request through **Mine → Customer Service Center** or `privacy@fitdays.com` asking for:

1. continuous API access for the account's own measurement history;
2. API documentation and authentication details;
3. availability in Chile;
4. supported fields and update frequency.

This should not block implementation. Treat it as a parallel attempt to replace the unofficial client with a supported interface later.

## Routes that are poor fits

- **Google Fit:** Fitdays can write to it, but Google's Fit APIs have been in migration toward Health Connect and are a poor foundation for a new server integration.
- **Samsung Health:** the data path returns to an Android-local SDK and adds no useful server API for this dashboard.
- **Apple Health:** on-device only and irrelevant to the current Android setup.
- **Manual CSV export or Drive sync:** suitable for backfill, not for automatic ingestion.
- **Buying another scale:** a Withings model would offer an official OAuth cloud API, but replacing working hardware is unnecessary before testing the routes above.

## Proposed implementation sequence

No production source should be selected solely from documentation. Use the following short proofs, in order:

1. **Fitdays cloud proof:** run a read-only `fitdays-api` probe and compare five readings and all fields against the Fitdays app.
2. **Fitbit bridge proof:** if the private API is rejected on maintenance grounds, enable Fitdays → Fitbit, take one measurement, and confirm both weight and body fat appear in Fitbit with the correct local time.
3. **Bluetooth compatibility proof:** run `ble-scale-sync scan` on the Windows laptop while standing on the scale. Record the advertised name, matched adapter, and whether impedance is available.

Choose after those tests:

- Use **direct Fitdays cloud** when low setup effort and the full vendor record matter most.
- Use **Fitbit** when weight/body-fat trends and a documented API matter more than setup effort and the complete record.
- Use **direct BLE** when eliminating vendor/cloud dependence is the priority and compatible always-on hardware is available.

The database and Body tab can stay source-neutral. Only the ingest adapter and setup documentation need to change. During a transition, tag each row's `source` value (`fitbit`, `fitdays_cloud`, `ble_scale_sync`, or `health_connect`) and keep the natural timestamp upsert so a proof run cannot create duplicates.

## Sources

[^1]: Fitdays, [FAQ: connect Fitbit](https://online.fitdays.cn/app/faq?language=en&source=0).
[^2]: Fitbit, [Web API Explorer: Body endpoints](https://dev.fitbit.com/build/reference/web-api/explore/).
[^3]: Fitdays, [Privacy policy: Fitbit synchronization fields](https://online.fitdays.cn/app/privacy).
[^4]: Fitbit, [Web API schema](https://dev.fitbit.com/build/reference/web-api/explore/fitbit-web-api-swagger.json); body log records include date and time.
[^5]: Fitdays, [How to measure: offline measurement and later sync](https://fitdays.org/docs/user-manual/how-to-measure).
[^6]: Fitdays, [FAQ: server-backed history](https://online.fitdays.cn/app/faq?language=en).
[^7]: Rodrigo Roque, [`fitdays-api`](https://github.com/roquerodrigo/fitdays-api) and [npm package](https://www.npmjs.com/package/fitdays-api).
[^8]: AboveColin, [unofficial Fitdays Python client](https://github.com/AboveColin/fitdays).
[^9]: BLE Scale Sync, [project overview and deployment options](https://blescalesync.dev/).
[^10]: BLE Scale Sync, [supported scales](https://blescalesync.dev/guide/supported-scales).
[^11]: BLE Scale Sync, [webhook exporter](https://blescalesync.dev/exporters#webhook).
[^12]: ICOMON, [Fitdays scale instruction manual](https://fccid.io/2AP3Q-FI2019LB-I/User-Manual/user-manual-7051428.pdf).
[^13]: BLE Scale Sync, [FAQ: Docker on Windows/macOS](https://blescalesync.dev/faq#docker-on-macos-or-windows).
[^14]: BLE Scale Sync, [body-composition formulas and limitations](https://blescalesync.dev/body-composition).
[^15]: BLE Scale Sync, [FAQ: offline use and retry behavior](https://blescalesync.dev/faq#does-it-work-offline-without-wifi).
[^16]: openScale, [supported scales](https://github.com/oliexdev/openScale/wiki/Supported-scales-in-openScale).
[^17]: openScale Sync, [README](https://github.com/oliexdev/openScale-sync/blob/master/README.md).
[^18]: HC Webhook, [project overview](https://github.com/mcnaveen/health-connect-webhook).
[^19]: HC Webhook, [features](https://github.com/mcnaveen/health-connect-webhook/blob/main/docs/features.md) and [webhook contract](https://github.com/mcnaveen/health-connect-webhook/blob/main/docs/webhook.md).
[^20]: HCGateway, [project overview](https://github.com/ShuchirJ/HCGateway).
[^21]: Rodrigo Roque, [`fitdays-mcp-server`](https://github.com/roquerodrigo/fitdays-mcp-server).
[^22]: nibu147, [Fitdays MCP Cloudflare Worker](https://glama.ai/mcp/servers/nibu147/fitdays-mcp-worker).
[^23]: Fitdays, [Privacy policy: access, extraction, and migration](https://online.fitdays.cn/app/privacy).
