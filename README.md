# Varaha ARR Partner App — Analytics Dashboard

Live analytics for the Varaha ARR (Afforestation, Reforestation, Revegetation) field partner app.
Connects directly to BigQuery and refreshes automatically — no manual exports needed.

**Live dashboard →** https://varaha-arr-dashboard.streamlit.app

<img width="1430" height="785" alt="image" src="https://github.com/user-attachments/assets/4d763bb8-e4fb-473e-9f8a-784ee10d2be6" />

---

## What it shows

<img width="1411" height="858" alt="image" src="https://github.com/user-attachments/assets/960720a1-4ea1-4125-bba7-9bf942b2ddd4" />


| Section | What you get |
|---|---|
| **Insights** | Auto-generated action items: OTP rate, worker failures, churn, crashes — with recommended actions |
| **Overview** | KPIs vs prior period, daily installs/active-users/error trends |
| **Farm Funnel** | Stepped funnel: Started → Form Filled → OTP Signed; drop-off breakdown |
| **User Journeys** | Sankey diagram of real screen flows; exit-ratio heatmap |
| **Errors & Sync** | Worker failure breakdown by type and error message; daily error trend |
| **Crashes** | Crashlytics breakdown by category, daily trend, fatal vs non-fatal, issue detail |

A **date-range picker** (default: last 7 days) controls every chart. Quick-select presets: 7d / 30d / 90d.

<img width="1404" height="869" alt="image" src="https://github.com/user-attachments/assets/467aceb1-b5ad-4ea0-a3eb-a4069637c33b" />

<img width="1387" height="855" alt="image" src="https://github.com/user-attachments/assets/f9c85518-21f9-48dd-9c24-8a493d87d7fa" />

---

## System architecture

```
┌─────────────────────────────────────────────────┐
│  Android App (Varaha ARR Partner App)           │
│  ├─ Firebase Analytics SDK → GA4 events         │
│  └─ Firebase Crashlytics SDK → crash reports    │
└───────────────┬─────────────────────────────────┘
                │ automatic daily export
                ▼
┌─────────────────────────────────────────────────┐
│  Google BigQuery  (project: arr-partner-app)    │
│                                                 │
│  analytics_445901335.events_YYYYMMDD  ← GA4    │
│  analytics_445901335.events_intraday_YYYYMMDD  │
│                                                 │
│  firebase_crashlytics                           │
│  └─ com_varaha_arrapp_ANDROID         ← Crashes│
└───────────────┬─────────────────────────────────┘
                │ service account (read-only)
                ▼
┌─────────────────────────────────────────────────┐
│  Streamlit app  (app.py)                        │
│  ├─ Auth: SA creds (cloud) / gcloud ADC (local) │
│  ├─ Queries parameterised by date range         │
│  ├─ @st.cache_data TTL 30 min                   │
│  └─ Plotly charts + auto-insights engine        │
└───────────────┬─────────────────────────────────┘
                │ deployed via GitHub
                ▼
┌─────────────────────────────────────────────────┐
│  Streamlit Community Cloud                      │
│  github.com/rohyeeet/varaha-arr-dashboard       │
│  Secrets: injected via Settings → Secrets       │
└─────────────────────────────────────────────────┘
```

### Data flow details

<img width="1380" height="885" alt="image" src="https://github.com/user-attachments/assets/bc7fa386-0203-4af3-b3a5-cc5abf7c3317" />

1. Firebase SDK fires events on the Android device.
2. GA4 exports a new `events_YYYYMMDD` table to BigQuery each day (plus intraday tables during the day).
3. Crashlytics writes to a single partitioned table (`com_varaha_arrapp_ANDROID`) — not sharded.
4. The Streamlit app queries BigQuery on page load; results are cached for 30 minutes.
5. All queries are parameterised by `start_date` / `end_date` from the UI date picker.
6. Wildcard table filter uses `_TABLE_SUFFIX BETWEEN 'YYYYMMDD' AND 'YYYYMMDD'` — this naturally excludes `events_intraday_*` tables because their suffix starts with `i` (ASCII 105 > `9` ASCII 57).

<img width="1375" height="906" alt="image" src="https://github.com/user-attachments/assets/f5b3051a-3602-4472-91b3-0a76eb9d0690" />

---

## Key metrics explained

### Farm onboarding (Q2-2026 flow change)

| Event | Meaning |
|---|---|
| `farm_onboarding_started` | User opens the farm onboarding flow |
| `farm_updated` | Form data submitted / synced to server ("form filled" proxy) |
| `farm_created` | **CRA/FPIC OTP signed** — farm fully onboarded (gate tightened Q2-2026) |

Before Q2-2026, `farm_created` fired on form sync. From Q2-2026 it only fires when the
physical consent OTP is signed. Farms between `farm_updated` and `farm_created` are in the
**ops pipeline** awaiting field agent follow-up — not dropped users.

### OTP errors proxy
`pdf_conversion_error` events = failed OTP document generation. Each one directly
blocks a farm from completing CRA/FPIC consent. There is no explicit `otp_sent`/`otp_failed`
event in GA4 (instrumentation gap — P0 to add).

### Background workers

| Worker | Purpose |
|---|---|
| `ConvertMediaToPDFWorker` | Photo → PDF for OTP documents |
| `UploadMediaWorker` | Upload farm/tree photos |
| `SaplingSyncWorker` | Sync sapling data (added Q1-2026) |
| `MediaConversionWorker` | Legacy (Q4-2025 only) |

Workers auto-retry ~5× before recording a `worker_fail` event. Failures here are
**post-retry final failures** — they represent real data sync loss.

<img width="1365" height="846" alt="image" src="https://github.com/user-attachments/assets/67fae386-bb60-47e0-a217-20f7fc7e2835" />

### Not yet instrumented (coverage gaps)

These features have **zero custom GA4 events** — their usage is invisible:

- LSC (Land Survey Completion)
- Monitoring rounds
- Soil sampling
- Tasks / Activities
- OTP delivery funnel (`otp_sent`, `otp_delivered`, `otp_failed`)

---

## Local development

### Prerequisites
- Python 3.9+
- `gcloud` CLI authenticated: `gcloud auth application-default login`
- Access to `arr-partner-app` BigQuery project

### Setup

```bash
git clone https://github.com/rohyeeet/varaha-arr-dashboard.git
cd varaha-arr-dashboard
pip install -r requirements.txt
streamlit run app.py
```

The app falls back to `google.auth.default()` (gcloud ADC) when no `st.secrets` are present.

---

## Streamlit Cloud deployment

1. Push to `main` branch of `github.com/rohyeeet/varaha-arr-dashboard`.
2. In Streamlit Cloud → **Settings → Secrets**, paste:

```toml
[gcp_service_account]
type = "service_account"
project_id = "arr-partner-app"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "arr-app-analytics@arr-partner-app.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

3. The service account needs two IAM roles on `arr-partner-app`:
   - `roles/bigquery.dataViewer`
   - `roles/bigquery.jobUser`

Streamlit Cloud auto-redeploys on every push to `main`. No manual steps needed for new data —
BigQuery tables grow automatically as Firebase exports daily.

---

## Repository structure

```
varaha-arr-dashboard/
├── app.py                        # Full Streamlit app
├── requirements.txt              # Python dependencies
├── README.md                     # This file
├── .gitignore                    # secrets.toml excluded
└── .streamlit/
    ├── config.toml               # Theme (blue #2563eb)
    └── secrets.toml              # Local only — never committed
```

---

## Dependencies

```
streamlit>=1.35.0
google-cloud-bigquery>=3.11.0
google-auth>=2.23.0
pandas>=2.0.0
plotly>=5.18.0
db-dtypes>=1.1.0
```
