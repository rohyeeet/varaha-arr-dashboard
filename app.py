import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from google.cloud import bigquery
import google.auth

PROJECT     = "arr-partner-app"
GA4_TABLE   = f"`{PROJECT}.analytics_445901335.events_*`"
CRASH_TABLE = f"`{PROJECT}.firebase_crashlytics.com_varaha_arrapp_ANDROID`"

st.set_page_config(
    page_title="Varaha ARR App — Analytics",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .block-container{padding-top:1.2rem;padding-bottom:2rem}
  h1{font-size:1.4rem!important;font-weight:800!important}
  h2{font-size:1.05rem!important;font-weight:700!important;margin-top:1.1rem!important}
  h3{font-size:.9rem!important;font-weight:600!important}
  .stMetric{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:.55rem .9rem}
  .stMetric label{font-size:.72rem!important;color:#6b7280!important}
  div[data-testid="stHorizontalBlock"]{gap:.4rem}
  .icard{padding:11px 14px;border-radius:7px;margin:.35rem 0;font-size:.8rem;line-height:1.55}
  .i-alert{background:#fef2f2;border-left:4px solid #dc2626;color:#7f1d1d}
  .i-warn {background:#fffbeb;border-left:4px solid #d97706;color:#78350f}
  .i-good {background:#f0fdf4;border-left:4px solid #16a34a;color:#14532d}
  .i-info {background:#eff6ff;border-left:4px solid #2563eb;color:#1e3a8a}
  .ititle{font-weight:700;font-size:.83rem;margin-bottom:3px}
  .iaction{font-style:italic;margin-top:5px;border-top:1px solid rgba(0,0,0,.08);padding-top:4px}
  .pill{display:inline-block;padding:1px 8px;border-radius:12px;font-size:.7rem;font-weight:600;margin-right:4px}
  .p-red{background:#fee2e2;color:#dc2626}
  .p-amber{background:#fef3c7;color:#d97706}
  .p-green{background:#dcfce7;color:#16a34a}
</style>
""", unsafe_allow_html=True)

# ── Auth ──────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to BigQuery…")
def get_client():
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials
        info = dict(st.secrets["gcp_service_account"])
        if "\\n" in info.get("private_key", ""):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        return bigquery.Client(credentials=creds, project=PROJECT)
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return bigquery.Client(credentials=creds, project=PROJECT)

client = get_client()

# ── Date helpers ──────────────────────────────────────────────────────
def ga4_where(start: date, end: date) -> str:
    # BETWEEN naturally excludes intraday_ suffixes ('i' > '9' in ASCII)
    return f"_TABLE_SUFFIX BETWEEN '{start:%Y%m%d}' AND '{end:%Y%m%d}'"

def crash_where(start: date, end: date) -> str:
    return (f"event_timestamp BETWEEN TIMESTAMP('{start:%Y-%m-%d}') "
            f"AND TIMESTAMP('{(end + timedelta(days=1)):%Y-%m-%d}')")

# ── Queries ───────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def load_summary(start: date, end: date) -> pd.Series:
    w = ga4_where(start, end)
    sql = f"""
    SELECT
      COUNT(DISTINCT CASE WHEN event_name='first_open'    THEN user_pseudo_id END) AS new_installs,
      COUNT(DISTINCT CASE WHEN event_name='app_remove'    THEN user_pseudo_id END) AS uninstalls,
      COUNT(DISTINCT CASE WHEN event_name='session_start' THEN user_pseudo_id END) AS active_users,
      COUNT(DISTINCT CASE WHEN event_name='login'         THEN user_pseudo_id END) AS logins,
      COUNT(DISTINCT CASE WHEN event_name='session_start'
        THEN (SELECT ep.value.int_value FROM UNNEST(event_params) ep
               WHERE ep.key='ga_session_id' LIMIT 1) END) AS sessions,

      COUNT(DISTINCT CASE WHEN event_name='farm_onboarding_started'            THEN user_pseudo_id END) AS farm_started,
      COUNT(DISTINCT CASE WHEN event_name='farm_updated'                       THEN user_pseudo_id END) AS farm_form_filled,
      COUNT(DISTINCT CASE WHEN event_name='farm_created'                       THEN user_pseudo_id END) AS farm_otp_signed,
      COUNT(DISTINCT CASE WHEN event_name='farmer_onboarding_started'          THEN user_pseudo_id END) AS farmer_started,
      COUNT(DISTINCT CASE WHEN event_name='farmer_created'                     THEN user_pseudo_id END) AS farmer_done,
      COUNT(DISTINCT CASE WHEN event_name='plantation_kyari_onboarding_started' THEN user_pseudo_id END) AS plantation_started,
      COUNT(DISTINCT CASE WHEN event_name='plantation_kyari_created'           THEN user_pseudo_id END) AS plantation_done,
      COUNT(DISTINCT CASE WHEN event_name='retro_kyari_onboarding_started'     THEN user_pseudo_id END) AS retro_started,
      COUNT(DISTINCT CASE WHEN event_name='retro_kyari_created'                THEN user_pseudo_id END) AS retro_done,

      COUNT(CASE WHEN event_name='sapling_tree_auto_geotag'    THEN 1 END) AS auto_geo,
      COUNT(CASE WHEN event_name='sapling_tree_manual_geotag'  THEN 1 END) AS manual_geo,

      COUNT(CASE WHEN event_name='pdf_conversion_error'        THEN 1 END) AS pdf_errors,
      COUNT(CASE WHEN event_name='app_update_error'            THEN 1 END) AS update_errors,
      COUNT(CASE WHEN event_name='network_request_failure'     THEN 1 END) AS net_failures,
      COUNT(CASE WHEN event_name='worker_fail'                 THEN 1 END) AS worker_fails
    FROM {GA4_TABLE}
    WHERE {w}
    """
    return client.query(sql).to_dataframe().iloc[0]

@st.cache_data(ttl=1800, show_spinner=False)
def load_daily(start: date, end: date) -> pd.DataFrame:
    w = ga4_where(start, end)
    sql = f"""
    SELECT
      PARSE_DATE('%Y%m%d', _TABLE_SUFFIX)                                                              AS day,
      COUNT(DISTINCT CASE WHEN event_name='first_open'             THEN user_pseudo_id END)            AS new_installs,
      COUNT(DISTINCT CASE WHEN event_name='app_remove'             THEN user_pseudo_id END)            AS uninstalls,
      COUNT(DISTINCT CASE WHEN event_name='session_start'          THEN user_pseudo_id END)            AS active_users,
      COUNT(DISTINCT CASE WHEN event_name='farm_onboarding_started' THEN user_pseudo_id END)           AS farm_started,
      COUNT(DISTINCT CASE WHEN event_name='farm_created'           THEN user_pseudo_id END)            AS farm_otp_signed,
      COUNT(CASE WHEN event_name='pdf_conversion_error'            THEN 1 END)                         AS pdf_errors,
      COUNT(CASE WHEN event_name='worker_fail'                     THEN 1 END)                         AS worker_fails,
      COUNT(CASE WHEN event_name='network_request_failure'         THEN 1 END)                         AS net_failures
    FROM {GA4_TABLE}
    WHERE {w}
    GROUP BY day
    ORDER BY day
    """
    return client.query(sql).to_dataframe()

@st.cache_data(ttl=1800, show_spinner=False)
def load_worker_details(start: date, end: date) -> pd.DataFrame:
    w = ga4_where(start, end)
    sql = f"""
    SELECT
      IFNULL((SELECT ep.value.string_value FROM UNNEST(event_params) ep
               WHERE ep.key='worker_name' LIMIT 1), 'Unknown')   AS worker,
      IFNULL((SELECT ep.value.string_value FROM UNNEST(event_params) ep
               WHERE ep.key='error_message' LIMIT 1), '—')       AS error_msg,
      COUNT(*)                                                    AS failures,
      COUNT(DISTINCT user_pseudo_id)                              AS affected_users
    FROM {GA4_TABLE}
    WHERE {w} AND event_name = 'worker_fail'
    GROUP BY worker, error_msg
    ORDER BY failures DESC
    LIMIT 30
    """
    return client.query(sql).to_dataframe()

@st.cache_data(ttl=1800, show_spinner=False)
def load_screen_flow(start: date, end: date) -> pd.DataFrame:
    w = ga4_where(start, end)
    sql = f"""
    WITH screens AS (
      SELECT
        user_pseudo_id,
        (SELECT ep.value.int_value FROM UNNEST(event_params) ep
          WHERE ep.key = 'ga_session_id' LIMIT 1)                 AS session_id,
        event_timestamp,
        IFNULL(
          (SELECT ep.value.string_value FROM UNNEST(event_params) ep
            WHERE ep.key = 'firebase_screen_class' LIMIT 1), 'Unknown') AS screen
      FROM {GA4_TABLE}
      WHERE {w} AND event_name = 'screen_view'
    ),
    transitions AS (
      SELECT
        screen AS from_screen,
        LEAD(screen) OVER (
          PARTITION BY user_pseudo_id, session_id ORDER BY event_timestamp) AS to_screen,
        user_pseudo_id
      FROM screens
    )
    SELECT
      from_screen, to_screen,
      COUNT(*)                        AS transitions,
      COUNT(DISTINCT user_pseudo_id)  AS users
    FROM transitions
    WHERE to_screen IS NOT NULL AND from_screen != to_screen
    GROUP BY from_screen, to_screen
    HAVING COUNT(*) >= 3
    ORDER BY transitions DESC
    LIMIT 60
    """
    return client.query(sql).to_dataframe()

@st.cache_data(ttl=1800, show_spinner=False)
def load_crashes(start: date, end: date) -> pd.DataFrame:
    w = crash_where(start, end)
    sql = f"""
    SELECT
      DATE(event_timestamp) AS day,
      CASE
        WHEN issue_title LIKE '%NetworkRequest%' OR LOWER(issue_title) LIKE '%network%' THEN 'Network'
        WHEN issue_title LIKE '%SyncMedia%' OR issue_title LIKE '%MediaUpload%'
          OR issue_title LIKE '%ImageCompress%' THEN 'Media Sync'
        WHEN issue_title LIKE '%WorkerLogger%' OR LOWER(issue_title) LIKE '%worker%' THEN 'Worker'
        WHEN issue_title LIKE '%AppUpdate%' OR issue_title LIKE '%UpdateToLatest%' THEN 'App Update'
        WHEN issue_title LIKE '%Navigation%' THEN 'Navigation'
        WHEN issue_title LIKE '%Otp%' OR issue_title LIKE '%TokenExpiry%' THEN 'Login/OTP'
        WHEN issue_title LIKE '%TileProvider%' OR issue_title LIKE '%OfflineTile%' THEN 'Geo-Tag Tiles'
        ELSE 'Other'
      END AS category,
      issue_title,
      COUNT(*)                           AS crashes,
      COUNTIF(is_fatal)                  AS fatal_crashes,
      COUNT(DISTINCT installation_uuid)  AS devices
    FROM {CRASH_TABLE}
    WHERE {w}
    GROUP BY day, category, issue_title
    ORDER BY crashes DESC
    LIMIT 200
    """
    return client.query(sql).to_dataframe()

# ── Header + date picker ──────────────────────────────────────────────
st.title("🌱 Varaha ARR Partner App — Analytics")

hcol1, hcol2, hcol3 = st.columns([3, 1, 4])
with hcol1:
    date_range = st.date_input(
        "Date range",
        value=(date.today() - timedelta(days=6), date.today()),
        max_value=date.today(),
        format="DD/MM/YYYY",
    )
with hcol2:
    quick = st.selectbox("Quick select", ["Custom","Last 7d","Last 30d","Last 90d"], label_visibility="hidden")

# Apply quick-select presets
if quick == "Last 7d":
    start_date, end_date = date.today() - timedelta(days=6), date.today()
elif quick == "Last 30d":
    start_date, end_date = date.today() - timedelta(days=29), date.today()
elif quick == "Last 90d":
    start_date, end_date = date.today() - timedelta(days=89), date.today()
else:
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range[0] if isinstance(date_range, (list, tuple)) else date_range

if start_date > end_date:
    st.error("Start date must be on or before end date.")
    st.stop()

n_days    = (end_date - start_date).days + 1
prev_end  = start_date - timedelta(days=1)
prev_start = prev_end - timedelta(days=n_days - 1)

# ── Load all data ─────────────────────────────────────────────────────
with st.spinner(f"Loading data for {start_date:%d %b} – {end_date:%d %b %Y}…"):
    try:
        cur  = load_summary(start_date, end_date)
        prv  = load_summary(prev_start, prev_end)
        daily   = load_daily(start_date, end_date)
        workers = load_worker_details(start_date, end_date)
        flow    = load_screen_flow(start_date, end_date)
        crashes = load_crashes(start_date, end_date)
    except Exception as e:
        st.error(f"BigQuery error: {e}")
        st.stop()

# ── Helpers ───────────────────────────────────────────────────────────
def iv(s, key):
    return int(s.get(key, 0) or 0)

def pct_delta(curr, prev):
    if prev == 0:
        return None, None
    d   = curr - prev
    pct = d / prev * 100
    return f"{'+' if d>=0 else ''}{pct:.0f}%", d >= 0

def rate(num, denom):
    return round(num / max(denom, 1) * 100, 1)

# ── Insights engine ───────────────────────────────────────────────────
def build_insights(cur, prv, crash_df, n_days):
    items = []

    fs, ff, fo = iv(cur,"farm_started"), iv(cur,"farm_form_filled"), iv(cur,"farm_otp_signed")
    ni, un = iv(cur,"new_installs"), iv(cur,"uninstalls")
    pdf_err = iv(cur,"pdf_errors")
    wf  = iv(cur,"worker_fails")
    nf  = iv(cur,"net_failures")

    # Farm pipeline health
    if fs > 0:
        otp_r  = rate(fo, fs)
        fill_r = rate(ff, fs)
        pending = ff - fo
        if otp_r < 30:
            items.append(("alert", f"Farm OTP rate critical: {otp_r:.0f}%",
                f"{fo}/{fs} farms reached OTP sign-off. {pending} filled but unsigned — in ops pipeline.",
                "Ops team: follow up on {pending} pending farms. Check CRA connectivity for OTP delivery."))
        elif otp_r < 60:
            items.append(("warn", f"Farm OTP rate low: {otp_r:.0f}%",
                f"{fo}/{fs} farms signed. {pending} in-pipeline awaiting field consent.",
                "Monitor pending farms; escalate if count grows over 48h."))
        else:
            items.append(("good", f"Farm OTP rate healthy: {otp_r:.0f}%",
                f"{fo} farms fully onboarded, {ff} forms filled.", None))

    # PDF errors → OTP blocker
    if pdf_err > 0:
        sev = "alert" if pdf_err >= 10 else "warn"
        items.append((sev, f"{pdf_err} PDF conversion error{'s' if pdf_err>1 else ''}",
            "Each error is a failed OTP document generation — directly blocks CRA/FPIC signing.",
            "Check PDF generation service logs. Look for time-of-day pattern or specific app versions."))

    # Worker failures
    if wf > 30:
        items.append(("alert", f"{wf} worker failures — data sync at risk",
            f"Background workers failing {wf}× in {n_days} days. Field data may not be reaching the server.",
            "Review worker error messages in the Errors tab. Check retry exhaustion patterns."))
    elif wf > 0:
        items.append(("warn", f"{wf} worker failures detected",
            "Background sync failures can cause silent data loss if retry limit is hit.",
            "Check the Errors & Sync tab for breakdown by worker type."))

    # Churn
    if ni > 5:
        churn = rate(un, ni)
        ni_prev, un_prev = iv(prv,"new_installs"), iv(prv,"uninstalls")
        churn_prev = rate(un_prev, max(ni_prev,1))
        if churn > 70:
            items.append(("alert", f"High churn: {churn:.0f}% uninstall rate",
                f"{un} uninstalls vs {ni} installs. Previous period: {churn_prev:.0f}%.",
                "Investigate first-week experience. Consider in-app onboarding improvements."))
        elif ni > iv(prv,"new_installs") * 1.3:
            items.append(("good", f"Installs up {rate(ni-iv(prv,'new_installs'), iv(prv,'new_installs')):.0f}% vs prior period",
                f"{ni} installs vs {iv(prv,'new_installs')} in the previous {n_days}-day window.", None))

    # Crashes
    if not crash_df.empty:
        total_c = int(crash_df["crashes"].sum())
        fatal_c = int(crash_df["fatal_crashes"].sum())
        if fatal_c > 0:
            items.append(("alert", f"{fatal_c} fatal crash{'es' if fatal_c>1 else ''}",
                f"Total {total_c} crashes. Fatal crashes require immediate attention.",
                "Open Crashlytics → filter by is_fatal=true to get stack traces."))
        elif total_c > 100:
            top_cat = crash_df.groupby("category")["crashes"].sum().idxmax()
            items.append(("warn", f"{total_c} crashes this period",
                f"Top category: {top_cat}. Check Crashes tab for full breakdown.",
                "Prioritise fixing top-category crashes; each affects real field agents."))

    # Network failures
    if nf > 500:
        items.append(("info", f"{nf:,} network request failures",
            "High network failure rate typical in low-connectivity field areas.",
            "Verify offline retry queues are draining. Check if failures correlate with specific API endpoints."))

    if not items:
        items.append(("good", "All metrics look healthy",
            f"No critical issues in the {n_days}-day window.", None))

    return items

insights = build_insights(cur, prv, crashes, n_days)

# ── Insights panel ────────────────────────────────────────────────────
st.markdown(f"<small style='color:#6b7280'>"
            f"<b>{start_date:%d %b} – {end_date:%d %b %Y}</b> ({n_days}d) "
            f"· compared to {prev_start:%d %b} – {prev_end:%d %b}</small>",
            unsafe_allow_html=True)

with st.expander("🔍 Insights & Action Items", expanded=True):
    n_cols = min(len(insights), 3)
    icols  = st.columns(n_cols)
    for i, (typ, title, detail, action) in enumerate(insights):
        css = {"alert":"i-alert","warn":"i-warn","good":"i-good","info":"i-info"}[typ]
        act = f'<div class="iaction">→ {action}</div>' if action else ""
        with icols[i % n_cols]:
            st.markdown(
                f'<div class="icard {css}">'
                f'<div class="ititle">{title}</div>'
                f'<div>{detail}</div>{act}</div>',
                unsafe_allow_html=True)

st.markdown("")

# ── Tabs ──────────────────────────────────────────────────────────────
tabs = st.tabs(["📊 Overview", "🌾 Farm Funnel", "🗺️ User Journeys", "🔧 Errors & Sync", "💥 Crashes"])

# ═══ TAB 1 · OVERVIEW ════════════════════════════════════════════════
with tabs[0]:
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    def metric(col, label, key, invert=False):
        v    = iv(cur, key)
        pv   = iv(prv, key) or 1
        d    = v - pv
        pct  = d / pv * 100
        sign = "+" if d >= 0 else ""
        col.metric(label, f"{v:,}", f"{sign}{pct:.0f}%",
                   delta_color="inverse" if invert else "normal")

    metric(c1, "New Installs",  "new_installs")
    metric(c2, "Uninstalls",    "uninstalls", invert=True)
    metric(c3, "Active Users",  "active_users")
    metric(c4, "Sessions",      "sessions")
    metric(c5, "Farm OTP Signed","farm_otp_signed")
    metric(c6, "Worker Fails",  "worker_fails", invert=True)

    st.markdown("---")

    if not daily.empty:
        col_l, col_r = st.columns(2)

        with col_l:
            fig = go.Figure()
            fig.add_bar(x=daily["day"], y=daily["new_installs"], name="Installs", marker_color="#2563eb")
            fig.add_bar(x=daily["day"], y=daily["uninstalls"],   name="Uninstalls", marker_color="#fca5a5")
            fig.update_layout(barmode="group", title="Daily Installs vs Uninstalls",
                              height=300, margin=dict(t=35,b=10,l=0,r=0),
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            fig2 = px.area(daily, x="day", y="active_users",
                           title="Daily Active Users",
                           color_discrete_sequence=["#7c3aed"])
            fig2.update_traces(fill="tozeroy", line_color="#7c3aed", fillcolor="rgba(124,58,237,.12)")
            fig2.update_layout(height=300, margin=dict(t=35,b=10,l=0,r=0))
            st.plotly_chart(fig2, use_container_width=True)

        # Flow completions per day
        fig3 = go.Figure()
        fig3.add_scatter(x=daily["day"], y=daily["farm_started"],
                        name="Farm Started", mode="lines+markers",
                        line=dict(color="#93c5fd", width=1.5))
        fig3.add_scatter(x=daily["day"], y=daily["farm_otp_signed"],
                        name="Farm OTP Signed", mode="lines+markers",
                        line=dict(color="#2563eb", width=2))
        fig3.update_layout(title="Daily Farm Onboarding Funnel",
                           height=260, margin=dict(t=35,b=10,l=0,r=0),
                           legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig3, use_container_width=True)

    with st.expander("All flows — completion rates"):
        flows_data = [
            ("Farm (OTP gate)",   iv(cur,"farm_started"),       iv(cur,"farm_otp_signed")),
            ("Farmer",            iv(cur,"farmer_started"),     iv(cur,"farmer_done")),
            ("New Plantation",    iv(cur,"plantation_started"), iv(cur,"plantation_done")),
            ("Retro Kyari",       iv(cur,"retro_started"),      iv(cur,"retro_done")),
        ]
        fdf = pd.DataFrame(flows_data, columns=["Flow","Started","Completed"])
        fdf["Rate %"] = fdf.apply(lambda r: rate(r["Completed"], r["Started"]), axis=1)

        fig_f = px.bar(fdf, x="Flow", y=["Started","Completed"],
                       barmode="group",
                       color_discrete_map={"Started":"#bfdbfe","Completed":"#2563eb"})
        fig_f.update_layout(height=300, margin=dict(t=10,b=10,l=0,r=0),
                            legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_f, use_container_width=True)

        def color_rate(v):
            if isinstance(v, float):
                if v >= 75: return "color:#16a34a;font-weight:700"
                if v >= 50: return "color:#d97706;font-weight:600"
                return "color:#dc2626;font-weight:700"
            return ""
        st.dataframe(fdf.style.map(color_rate, subset=["Rate %"]),
                     use_container_width=True, hide_index=True)

# ═══ TAB 2 · FARM FUNNEL ══════════════════════════════════════════════
with tabs[1]:
    fs = iv(cur,"farm_started")
    ff = iv(cur,"farm_form_filled")
    fo = iv(cur,"farm_otp_signed")

    col_a, col_b = st.columns([2, 1])

    with col_a:
        fig_fn = go.Figure(go.Funnel(
            y=["Onboarding Started", "Form Filled<br>(farm_updated)", "OTP Signed<br>(farm_created)"],
            x=[fs, ff, fo],
            textinfo="value+percent initial",
            marker_color=["#bfdbfe","#60a5fa","#2563eb"],
            connector=dict(line=dict(color="#93c5fd", width=2)),
        ))
        fig_fn.update_layout(title="Farm Onboarding Funnel",
                             height=380, margin=dict(t=40,b=10,l=10,r=10))
        st.plotly_chart(fig_fn, use_container_width=True)

    with col_b:
        st.markdown("**Stage breakdown**")
        fill_r = rate(ff, fs)
        otp_r  = rate(fo, fs)
        otp_of_fill = rate(fo, ff)
        pending = max(ff - fo, 0)

        st.metric("Started", f"{fs:,}")
        st.metric("Form Fill Rate", f"{fill_r}%",
                  help="farm_updated ÷ farm_onboarding_started")
        st.metric("OTP Signed Rate", f"{otp_r}%",
                  help="farm_created ÷ farm_onboarding_started")
        st.metric("OTP of Filled", f"{otp_of_fill}%",
                  help="farm_created ÷ farm_updated")
        st.metric("Pending OTP", f"{pending:,}",
                  help="Farms with form filled but OTP not yet signed — in ops pipeline")

    st.markdown("---")

    # Drop-off breakdown
    d1 = fs - ff
    d2 = ff - fo
    drop_df = pd.DataFrame({
        "Drop-off stage": ["Started → Form not filled", "Form filled → OTP not signed"],
        "Users lost":     [d1, d2],
        "% of started":   [rate(d1,fs), rate(d2,fs)],
    })
    fig_drop = px.bar(drop_df, x="Drop-off stage", y="Users lost",
                      color="% of started", color_continuous_scale="Reds",
                      text="Users lost", title="Where farms drop off")
    fig_drop.update_layout(height=280, margin=dict(t=35,b=10,l=0,r=0),
                           coloraxis_showscale=False)
    st.plotly_chart(fig_drop, use_container_width=True)

    if iv(cur,"pdf_errors") > 0:
        st.info(f"**{iv(cur,'pdf_errors')} PDF errors** in this window — each blocks an OTP document from generating. "
                f"Check the Errors & Sync tab for details.")

    with st.expander("ℹ️ Flow change note (Q2-2026 onwards)"):
        st.markdown("""
        Before Q2-2026: `farm_created` fired when the form was synced to server.

        **From Q2-2026:** `farm_created` fires **only when CRA/FPIC OTP is signed** (harder gate).
        `farm_updated` is now the proxy for "form filled".

        Farms where form is filled but OTP not signed are real farms in the field ops pipeline —
        not lost users. The gap represents the consent process lag, not a UX problem.
        """)

# ═══ TAB 3 · USER JOURNEYS ════════════════════════════════════════════
with tabs[2]:
    st.subheader("Screen Navigation Flow")

    if flow.empty:
        st.info("No screen_view events found in this date range. Try a wider range.")
    else:
        # Build Sankey — shorten Activity/Fragment suffixes for readability
        def shorten(name: str) -> str:
            for suffix in ("Activity","Fragment","ViewModel","Screen"):
                name = name.replace(suffix, "")
            return name.strip() or "?"

        top40  = flow.head(40)
        all_sc = list(dict.fromkeys(
            top40["from_screen"].tolist() + top40["to_screen"].tolist()))
        idx    = {s: i for i, s in enumerate(all_sc)}
        labels = [shorten(s) for s in all_sc]

        fig_sk = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(
                pad=14, thickness=18,
                label=labels,
                color="#2563eb",
                hovertemplate="%{label}<extra></extra>",
            ),
            link=dict(
                source=[idx[r.from_screen] for _, r in top40.iterrows()],
                target=[idx[r.to_screen]   for _, r in top40.iterrows()],
                value=top40["transitions"].tolist(),
                color="rgba(37,99,235,.13)",
                hovertemplate="%{source.label} → %{target.label}<br>%{value} transitions<extra></extra>",
            )
        ))
        fig_sk.update_layout(
            title="User screen flow — top 40 transitions (width = frequency)",
            height=580, margin=dict(t=40,b=10,l=10,r=10))
        st.plotly_chart(fig_sk, use_container_width=True)

        st.markdown("---")
        col_j1, col_j2 = st.columns(2)

        with col_j1:
            st.subheader("Most-visited screens")
            # Count how often each screen appears as a source
            screen_freq = (
                flow.groupby("from_screen")["transitions"].sum()
                .sort_values(ascending=False).head(12).reset_index()
            )
            screen_freq.columns = ["Screen","Departures"]
            screen_freq["Screen"] = screen_freq["Screen"].apply(shorten)
            fig_sf = px.bar(screen_freq, x="Departures", y="Screen",
                            orientation="h", color_discrete_sequence=["#2563eb"])
            fig_sf.update_layout(height=380, margin=dict(t=10,b=10,l=0,r=0), yaxis_title="")
            st.plotly_chart(fig_sf, use_container_width=True)

        with col_j2:
            st.subheader("Top exit screens (no onward transition)")
            exits = (
                flow.groupby("to_screen")["transitions"].sum()
                .reset_index()
                .merge(
                    flow.groupby("from_screen")["transitions"].sum().reset_index()
                    .rename(columns={"from_screen":"to_screen","transitions":"departures"}),
                    on="to_screen", how="left"
                )
            )
            exits["departures"] = exits["departures"].fillna(0)
            exits["exit_ratio"] = exits["transitions"] / (exits["transitions"] + exits["departures"])
            exits = exits[exits["transitions"] > 2].sort_values("exit_ratio", ascending=False).head(10)
            exits["Screen"] = exits["to_screen"].apply(shorten)
            fig_ex = px.bar(exits, x="exit_ratio", y="Screen",
                            orientation="h", color_discrete_sequence=["#dc2626"],
                            labels={"exit_ratio":"Exit ratio"})
            fig_ex.update_layout(height=380, margin=dict(t=10,b=10,l=0,r=0),
                                 xaxis_tickformat=".0%", yaxis_title="")
            st.plotly_chart(fig_ex, use_container_width=True)

        with st.expander("Raw transition table"):
            disp = flow.copy()
            disp["from_screen"] = disp["from_screen"].apply(shorten)
            disp["to_screen"]   = disp["to_screen"].apply(shorten)
            st.dataframe(disp.rename(columns={
                "from_screen":"From","to_screen":"To",
                "transitions":"Count","users":"Users"}),
                use_container_width=True, hide_index=True)

# ═══ TAB 4 · ERRORS & SYNC ════════════════════════════════════════════
with tabs[3]:
    e1,e2,e3,e4 = st.columns(4)
    e1.metric("Worker Fails",   f"{iv(cur,'worker_fails'):,}",
              f"{iv(cur,'worker_fails')-iv(prv,'worker_fails'):+,} vs prev",
              delta_color="inverse")
    e2.metric("PDF Errors",     f"{iv(cur,'pdf_errors'):,}",
              delta_color="off")
    e3.metric("Network Fails",  f"{iv(cur,'net_failures'):,}",
              delta_color="off")
    e4.metric("Update Errors",  f"{iv(cur,'update_errors'):,}",
              delta_color="off")

    st.markdown("---")

    if not daily.empty:
        fig_err = go.Figure()
        fig_err.add_scatter(x=daily["day"], y=daily["pdf_errors"],
                           name="PDF Errors", mode="lines+markers",
                           line=dict(color="#dc2626", width=2))
        fig_err.add_scatter(x=daily["day"], y=daily["worker_fails"],
                           name="Worker Fails", mode="lines+markers",
                           line=dict(color="#d97706", width=2))
        fig_err.add_scatter(x=daily["day"], y=daily["net_failures"],
                           name="Network Fails", mode="lines",
                           line=dict(color="#9ca3af", width=1, dash="dot"))
        fig_err.update_layout(title="Daily Error Events",
                              height=280, margin=dict(t=35,b=10,l=0,r=0),
                              legend=dict(orientation="h", y=-0.22))
        st.plotly_chart(fig_err, use_container_width=True)

    if not workers.empty:
        st.subheader("Worker Failure Breakdown")

        # Bar by worker type
        by_worker = workers.groupby("worker")["failures"].sum().reset_index().sort_values("failures", ascending=False)
        fig_w = px.bar(by_worker, x="failures", y="worker", orientation="h",
                       color="failures", color_continuous_scale="Oranges",
                       title="Failures by Worker")
        fig_w.update_layout(height=max(200, len(by_worker)*40+60),
                            margin=dict(t=35,b=10,l=0,r=0),
                            coloraxis_showscale=False, yaxis_title="")
        st.plotly_chart(fig_w, use_container_width=True)

        st.subheader("Top error messages")
        st.dataframe(
            workers.rename(columns={
                "worker":"Worker","error_msg":"Error Message",
                "failures":"Failures","affected_users":"Affected Users"}),
            use_container_width=True, hide_index=True)
    else:
        st.success("No worker failures in this date range.")

    with st.expander("ℹ️ Worker context"):
        st.markdown("""
        | Worker | Role |
        |---|---|
        | `ConvertMediaToPDFWorker` | Converts photos to PDF for OTP document — failure blocks signing |
        | `UploadMediaWorker` | Uploads farm/tree photos to server |
        | `SaplingSyncWorker` | Syncs sapling data (added Q1-2026) |
        | `MediaConversionWorker` | Legacy media worker (Q4-2025 only) |

        Workers retry automatically (~5× on average). Failures shown here are **final failures** after all retries.
        """)

# ═══ TAB 5 · CRASHES ══════════════════════════════════════════════════
with tabs[4]:
    if crashes.empty:
        st.success("No crashes in this date range.")
    else:
        total_c = int(crashes["crashes"].sum())
        fatal_c = int(crashes["fatal_crashes"].sum())
        devs_c  = int(crashes["devices"].sum())

        k1, k2, k3 = st.columns(3)
        k1.metric("Total Crashes",    f"{total_c:,}")
        k2.metric("Fatal Crashes",    f"{fatal_c:,}",
                  delta_color="off" if fatal_c == 0 else "inverse")
        k3.metric("Devices Affected", f"{devs_c:,}")

        st.markdown("---")

        cat_sum = (crashes.groupby("category")
                   .agg(crashes=("crashes","sum"), fatal=("fatal_crashes","sum"),
                        devices=("devices","sum"))
                   .reset_index().sort_values("crashes", ascending=False))

        col_ca, col_cb = st.columns(2)

        with col_ca:
            fig_cat = px.bar(cat_sum, x="crashes", y="category",
                             orientation="h",
                             color="fatal", color_continuous_scale=[[0,"#fca5a5"],[1,"#dc2626"]],
                             text="crashes", title="Crashes by Category")
            fig_cat.update_layout(height=350, margin=dict(t=35,b=10,l=0,r=0),
                                  coloraxis_showscale=False, yaxis_title="")
            st.plotly_chart(fig_cat, use_container_width=True)

        with col_cb:
            # Daily crash trend
            daily_c = (crashes.groupby("day")
                       .agg(crashes=("crashes","sum"), fatal=("fatal_crashes","sum"))
                       .reset_index())
            fig_dc = go.Figure()
            fig_dc.add_bar(x=daily_c["day"], y=daily_c["crashes"],
                           name="Total", marker_color="#fca5a5")
            fig_dc.add_scatter(x=daily_c["day"], y=daily_c["fatal"],
                               name="Fatal", mode="lines+markers",
                               line=dict(color="#dc2626", width=2))
            fig_dc.update_layout(title="Daily Crash Trend",
                                 height=350, margin=dict(t=35,b=10,l=0,r=0),
                                 legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig_dc, use_container_width=True)

        st.subheader("Crash detail — top issues")

        issue_sum = (crashes.groupby(["category","issue_title"])
                     .agg(crashes=("crashes","sum"), fatal=("fatal_crashes","sum"),
                          devices=("devices","sum"))
                     .reset_index().sort_values("crashes", ascending=False))

        def crash_row_color(row):
            if row["fatal"] > 0:
                return ["background-color:#fef2f2"]*len(row)
            return [""]*len(row)

        styled = (issue_sum.rename(columns={
            "category":"Category","issue_title":"Issue Title",
            "crashes":"Crashes","fatal":"Fatal","devices":"Devices"})
            .style.apply(crash_row_color, axis=1))

        st.dataframe(styled, use_container_width=True, hide_index=True)

        if fatal_c == 0:
            st.success("Zero fatal crashes in this period.")

# ── Footer ─────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Varaha · ARR Partner App Analytics · "
    f"BigQuery `{PROJECT}.analytics_445901335` + Firebase Crashlytics · "
    f"Data refreshes every 30 min · Built with Streamlit")
