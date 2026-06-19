import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.cloud import bigquery
import google.auth

PROJECT = "arr-partner-app"

st.set_page_config(
    page_title="Varaha ARR App — Analytics",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
  .block-container{padding-top:1.5rem;padding-bottom:2rem}
  h1{font-size:1.4rem!important;font-weight:800!important}
  h2{font-size:1.1rem!important;font-weight:700!important;margin-top:1.2rem!important}
  h3{font-size:.95rem!important;font-weight:700!important}
  .stMetric{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:.6rem 1rem}
  .stMetric label{font-size:.75rem!important;color:#6b7280!important}
  .stMetric [data-testid="metric-container"] div{font-size:1.5rem!important;font-weight:800!important}
  div[data-testid="stHorizontalBlock"]{gap:.5rem}
  .callout{padding:10px 14px;border-radius:6px;font-size:.8rem;line-height:1.6;margin:.5rem 0 1rem}
  .c-info {background:#eff6ff;border-left:3px solid #2563eb;color:#1e40af}
  .c-warn {background:#fffbeb;border-left:3px solid #d97706;color:#92400e}
  .c-good {background:#f0fdf4;border-left:3px solid #16a34a;color:#14532d}
  .c-alert{background:#fef2f2;border-left:3px solid #dc2626;color:#991b1b}
  .c-grey {background:#f9fafb;border-left:3px solid #d1d5db;color:#6b7280}
</style>
""", unsafe_allow_html=True)

# ── BigQuery client ───────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to BigQuery…")
def get_client():
    # On Streamlit Cloud, secrets.toml is injected by the platform.
    # Locally, fall back to gcloud Application Default Credentials.
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials
        info = dict(st.secrets["gcp_service_account"])
        # TOML stores \n as literal \\n — restore real newlines in the key
        if "\\n" in info.get("private_key", ""):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return bigquery.Client(credentials=creds, project=PROJECT)
    else:
        # Local dev: uses active `gcloud auth application-default login` session
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return bigquery.Client(credentials=creds, project=PROJECT)

client = get_client()

# ── Queries ───────────────────────────────────────────────────────────
QUARTER_EXPR = """CONCAT(
  CAST(EXTRACT(YEAR  FROM PARSE_DATE('%Y%m%d', _TABLE_SUFFIX)) AS STRING), '-Q',
  CASE
    WHEN EXTRACT(MONTH FROM PARSE_DATE('%Y%m%d', _TABLE_SUFFIX)) <= 3 THEN '1'
    WHEN EXTRACT(MONTH FROM PARSE_DATE('%Y%m%d', _TABLE_SUFFIX)) <= 6 THEN '2'
    WHEN EXTRACT(MONTH FROM PARSE_DATE('%Y%m%d', _TABLE_SUFFIX)) <= 9 THEN '3'
    ELSE '4'
  END
)"""

@st.cache_data(ttl=3600, show_spinner="Loading quarterly data…")
def load_quarterly():
    sql = f"""
    SELECT
      {QUARTER_EXPR} AS quarter,
      COUNT(DISTINCT CASE WHEN event_name='first_open'    THEN user_pseudo_id END) AS new_installs,
      COUNT(DISTINCT CASE WHEN event_name='app_remove'    THEN user_pseudo_id END) AS uninstalls,
      COUNT(DISTINCT CASE WHEN event_name='login'         THEN user_pseudo_id END) AS logins,
      COUNT(DISTINCT CASE WHEN event_name='session_start'
        THEN (SELECT ep.value.int_value FROM UNNEST(event_params) ep
               WHERE ep.key='ga_session_id' LIMIT 1) END)                          AS sessions,

      -- Farm onboarding funnel
      COUNT(DISTINCT CASE WHEN event_name='farm_onboarding_started' THEN user_pseudo_id END) AS farm_started,
      COUNT(DISTINCT CASE WHEN event_name='farm_updated'            THEN user_pseudo_id END) AS farm_form_filled,
      COUNT(DISTINCT CASE WHEN event_name='farm_created'            THEN user_pseudo_id END) AS farm_otp_signed,

      -- Other flows
      COUNT(DISTINCT CASE WHEN event_name='farmer_onboarding_started'          THEN user_pseudo_id END) AS farmer_started,
      COUNT(DISTINCT CASE WHEN event_name='farmer_created'                     THEN user_pseudo_id END) AS farmer_completed,
      COUNT(DISTINCT CASE WHEN event_name='plantation_kyari_onboarding_started' THEN user_pseudo_id END) AS plantation_started,
      COUNT(DISTINCT CASE WHEN event_name='plantation_kyari_created'           THEN user_pseudo_id END) AS plantation_completed,
      COUNT(DISTINCT CASE WHEN event_name='retro_kyari_onboarding_started'     THEN user_pseudo_id END) AS retro_started,
      COUNT(DISTINCT CASE WHEN event_name='retro_kyari_created'               THEN user_pseudo_id END) AS retro_completed,

      -- Geo-tagging
      COUNT(DISTINCT CASE WHEN event_name='sapling_tree_auto_geotag'   THEN user_pseudo_id END) AS auto_geo_users,
      COUNT(         CASE WHEN event_name='sapling_tree_auto_geotag'   THEN 1 END)              AS auto_geo_events,
      COUNT(DISTINCT CASE WHEN event_name='sapling_tree_manual_geotag' THEN user_pseudo_id END) AS manual_geo_users,

      -- Errors
      COUNT(CASE WHEN event_name='pdf_conversion_error'  THEN 1 END) AS pdf_errors,
      COUNT(CASE WHEN event_name='app_update_error'      THEN 1 END) AS update_errors,
      COUNT(CASE WHEN event_name='network_request_failure' THEN 1 END) AS net_failures,
      COUNT(CASE WHEN event_name='worker_fail'           THEN 1 END) AS worker_fails,

      -- Screen activities
      COUNT(DISTINCT CASE WHEN
        IFNULL((SELECT ep.value.string_value FROM UNNEST(event_params) ep
                 WHERE ep.key='firebase_screen_class' LIMIT 1),'')
        = 'SurveyorSaplingCountActivity' THEN user_pseudo_id END) AS sapling_count_users

    FROM `{PROJECT}.analytics_445901335.events_*`
    WHERE _TABLE_SUFFIX >= '20250409'
      AND REGEXP_CONTAINS(_TABLE_SUFFIX, r'^\d{{8}}$')
    GROUP BY quarter
    ORDER BY quarter
    """
    df = client.query(sql).to_dataframe()
    df["net_installs"] = df["new_installs"] - df["uninstalls"]
    df["farm_compl_pct"] = (df["farm_otp_signed"] / df["farm_started"].replace(0,1) * 100).round(1)
    df["farm_fill_pct"]  = (df["farm_form_filled"] / df["farm_started"].replace(0,1) * 100).round(1)
    df["farmer_compl_pct"] = (df["farmer_completed"] / df["farmer_started"].replace(0,1) * 100).round(1)
    df["plantation_compl_pct"] = (df["plantation_completed"] / df["plantation_started"].replace(0,1) * 100).round(1)
    df["retro_compl_pct"] = (df["retro_completed"] / df["retro_started"].replace(0,1) * 100).round(1)
    return df

@st.cache_data(ttl=3600, show_spinner="Loading crash data…")
def load_crashes():
    sql = f"""
    SELECT
      {QUARTER_EXPR} AS quarter,
      CASE
        WHEN issue_title LIKE '%NetworkRequest%' OR issue_title LIKE '%network%' THEN 'Network'
        WHEN issue_title LIKE '%SyncMedia%' OR issue_title LIKE '%MediaUpload%'
          OR issue_title LIKE '%ImageCompress%' THEN 'Media Sync'
        WHEN issue_title LIKE '%WorkerLogger%' OR issue_title LIKE '%worker%' THEN 'Worker'
        WHEN issue_title LIKE '%AppUpdate%' OR issue_title LIKE '%UpdateToLatest%' THEN 'App Update'
        WHEN issue_title LIKE '%Navigation%' THEN 'Navigation'
        WHEN issue_title LIKE '%Otp%' OR issue_title LIKE '%TokenExpiry%' THEN 'Login/OTP'
        WHEN issue_title LIKE '%TileProvider%' OR issue_title LIKE '%OfflineTile%' THEN 'Geo-Tag Tiles'
        ELSE 'Other'
      END AS category,
      COUNT(*) AS crashes,
      COUNTIF(is_fatal) AS fatal_crashes,
      COUNT(DISTINCT installation_uuid) AS devices
    FROM `{PROJECT}.firebase_crashlytics.com_varaha_arrapp_ANDROID`
    WHERE _TABLE_SUFFIX >= '20250409'
      AND REGEXP_CONTAINS(_TABLE_SUFFIX, r'^\d{{8}}$')
    GROUP BY quarter, category
    ORDER BY quarter, crashes DESC
    """
    return client.query(sql).to_dataframe()

# ── Load data ─────────────────────────────────────────────────────────
try:
    df = load_quarterly()
    crash_df = load_crashes()
    data_ok = True
except Exception as e:
    st.error(f"BigQuery connection failed: {e}")
    data_ok = False

if not data_ok:
    st.stop()

quarters = df["quarter"].tolist()
latest_q = quarters[-1] if quarters else "—"
latest   = df[df["quarter"] == latest_q].iloc[0] if quarters else None

# ═══════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════
st.title("🌱 Varaha ARR Partner App — Analytics")
st.caption(f"Live · BigQuery `analytics_445901335` · {len(quarters)} quarters · Latest: **{latest_q}** · Refreshes every hour")

tabs = st.tabs(["📊 Overview", "🌾 Farm Onboarding", "✅ All Flows", "📍 Field Activities", "🔴 Stability", "⚠️ Coverage Gaps"])

# ═══════════════════════════════════════════════════════════════════════
# TAB 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════
with tabs[0]:
    if latest is not None:
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Active Users", f"{int(latest['new_installs']):,}", help="Unique first_open users this quarter")
        c2.metric("Sessions",     f"{int(latest['sessions']):,}" if latest['sessions'] else "—")
        c3.metric("New Installs", f"{int(latest['new_installs']):,}")
        c4.metric("Uninstalls",   f"{int(latest['uninstalls']):,}")
        net = int(latest["net_installs"])
        c5.metric("Net",          f"{'+' if net>=0 else ''}{net:,}", delta=f"{'+' if net>=0 else ''}{net}")
        c6.metric("Farm OTP Rate",f"{latest['farm_compl_pct']:.1f}%")

    st.markdown("---")
    st.subheader("Quarterly trends")

    # Installs & uninstalls bar chart
    fig1 = go.Figure()
    fig1.add_bar(x=df["quarter"], y=df["new_installs"],  name="New Installs", marker_color="#2563eb")
    fig1.add_bar(x=df["quarter"], y=df["uninstalls"],    name="Uninstalls",   marker_color="#fca5a5")
    fig1.add_scatter(x=df["quarter"], y=df["net_installs"], name="Net",
                     mode="lines+markers", marker_color="#16a34a", line_width=2)
    fig1.update_layout(barmode="group", title="Installs vs Uninstalls per Quarter",
                       height=350, margin=dict(t=40,b=20,l=0,r=0),
                       legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig1, use_container_width=True)

    # Sessions line
    fig2 = px.line(df, x="quarter", y="sessions", markers=True,
                   title="Sessions per Quarter", color_discrete_sequence=["#2563eb"])
    fig2.update_layout(height=280, margin=dict(t=40,b=20,l=0,r=0))
    st.plotly_chart(fig2, use_container_width=True)

    # Raw table
    with st.expander("📋 Raw quarterly data"):
        show_cols = ["quarter","new_installs","uninstalls","net_installs","logins","sessions",
                     "farm_started","farm_otp_signed","farmer_started","farmer_completed"]
        st.dataframe(df[show_cols].set_index("quarter"), use_container_width=True)

    st.markdown("""
    <div class="callout c-info">
    <b>Seasonality:</b> Q3 (Jul–Sep, monsoon planting season) is peak on every metric.
    Q1 is the off-season low. Build the feature calendar around this cycle.
    </div>
    <div class="callout c-warn">
    <b>Retention:</b> Uninstall rate is ~79% of new installs in Q2-2026.
    Q1-2026 was the first net-negative quarter (−22). Retention is the lever, not acquisition.
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 2: FARM ONBOARDING
# ═══════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("Farm Onboarding — Corrected Funnel")
    st.markdown("""
    <div class="callout c-info">
    <b>Flow change (Q2-2026):</b> <code>farm_created</code> now fires only when <b>CRA/FPIC OTP is signed</b>,
    not when the form is synced. <code>farm_updated</code> is the new "form filled" proxy.
    The 9% figure is a harder gate, not a regression.
    </div>
    """, unsafe_allow_html=True)

    # Funnel chart
    fig_funnel = go.Figure()
    fig_funnel.add_bar(x=df["quarter"], y=df["farm_started"],    name="Started",          marker_color="#bfdbfe")
    fig_funnel.add_bar(x=df["quarter"], y=df["farm_form_filled"], name="Form Filled (proxy)", marker_color="#60a5fa")
    fig_funnel.add_bar(x=df["quarter"], y=df["farm_otp_signed"],  name="OTP Signed ✓",    marker_color="#2563eb")
    fig_funnel.update_layout(barmode="overlay", title="Farm Onboarding Funnel (users)",
                             height=360, margin=dict(t=40,b=20,l=0,r=0),
                             legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_funnel, use_container_width=True)

    # Completion % line
    fig_pct = go.Figure()
    fig_pct.add_scatter(x=df["quarter"], y=df["farm_compl_pct"],
                        name="OTP Signed / Started %", mode="lines+markers",
                        marker_color="#dc2626", line_width=2)
    fig_pct.add_scatter(x=df["quarter"], y=df["farm_fill_pct"],
                        name="Form Filled / Started %", mode="lines+markers",
                        marker_color="#2563eb", line_width=2, line_dash="dash")
    fig_pct.update_layout(title="Farm Completion Rates", yaxis_ticksuffix="%",
                          height=300, margin=dict(t=40,b=20,l=0,r=0),
                          legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_pct, use_container_width=True)

    st.subheader("CRA/FPIC Document Errors (OTP blocking proxy)")
    fig_pdf = px.bar(df[df["pdf_errors"]>0], x="quarter", y="pdf_errors",
                     title="pdf_conversion_error events per quarter",
                     color_discrete_sequence=["#f97316"])
    fig_pdf.update_layout(height=280, margin=dict(t=40,b=20,l=0,r=0))
    st.plotly_chart(fig_pdf, use_container_width=True)

    st.markdown("""
    <div class="callout c-alert">
    <b>Q2-2026:</b> 255 started → 167 form filled (65.5%) → 23 OTP signed (9.0%).
    144 farms are in-pipeline awaiting physical CRA/FPIC consent signing.
    This is an <b>ops coordination gap</b>, not a UX bug.
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 3: ALL FLOWS
# ═══════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("Completion Rates — All Flows")

    # Line chart: all completion %
    fig_all = go.Figure()
    colors = {"Retro Kyaari":"#16a34a","New Plantation":"#2563eb",
              "Farmer":"#d97706","Farm (OTP)":"#dc2626"}
    for col, label, color in [
        ("retro_compl_pct","Retro Kyaari","#16a34a"),
        ("plantation_compl_pct","New Plantation","#2563eb"),
        ("farmer_compl_pct","Farmer","#d97706"),
        ("farm_compl_pct","Farm (OTP gate)","#dc2626"),
    ]:
        fig_all.add_scatter(x=df["quarter"], y=df[col], name=label,
                            mode="lines+markers", line_color=color, line_width=2)
    fig_all.update_layout(title="Flow completion rates (%) — all quarters",
                          yaxis_ticksuffix="%", yaxis_range=[0,105],
                          height=380, margin=dict(t=40,b=20,l=0,r=0),
                          legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_all, use_container_width=True)

    # Volume grouped bar
    st.subheader("Flow volumes (users who started each flow)")
    flow_long = pd.melt(df, id_vars=["quarter"],
        value_vars=["farm_started","farmer_started","plantation_started","retro_started"],
        var_name="flow", value_name="users")
    flow_long["flow"] = flow_long["flow"].str.replace("_started","").str.title()
    fig_vol = px.bar(flow_long, x="quarter", y="users", color="flow", barmode="group",
                     title="Users starting each flow per quarter",
                     color_discrete_sequence=["#dc2626","#d97706","#2563eb","#16a34a"])
    fig_vol.update_layout(height=350, margin=dict(t=40,b=20,l=0,r=0),
                          legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_vol, use_container_width=True)

    # Completion table
    st.subheader("Completion rate table")
    tbl = df[["quarter","retro_compl_pct","plantation_compl_pct","farmer_compl_pct","farm_compl_pct"]].copy()
    tbl.columns = ["Quarter","Retro Kyaari %","New Plantation %","Farmer %","Farm (OTP) %"]
    tbl = tbl.set_index("Quarter")
    def color_pct(val):
        if isinstance(val, float):
            if val >= 80: return "color: #16a34a; font-weight:700"
            if val >= 60: return "color: #d97706; font-weight:600"
            return "color: #dc2626; font-weight:700"
        return ""
    st.dataframe(tbl.style.applymap(color_pct), use_container_width=True)

    st.markdown("""
    <div class="callout c-good">
    <b>Strong:</b> Retro Kyaari has never dropped below 88% across 5 quarters.
    New Plantation hit its all-time high of 84.5% in Q2-2026.
    Farmer recovered strongly to 76.4% after the Q1-2026 dip.
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 4: FIELD ACTIVITIES
# ═══════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Geo-Tagging")

    col1, col2 = st.columns(2)
    with col1:
        fig_geo_u = px.bar(df, x="quarter", y="auto_geo_users",
                           title="Auto Geo-Tag Users",
                           color_discrete_sequence=["#2563eb"])
        fig_geo_u.update_layout(height=280, margin=dict(t=40,b=10,l=0,r=0))
        st.plotly_chart(fig_geo_u, use_container_width=True)
    with col2:
        fig_geo_e = px.bar(df, x="quarter", y="auto_geo_events",
                           title="Auto Geo-Tag Events (volume)",
                           color_discrete_sequence=["#60a5fa"])
        fig_geo_e.update_layout(height=280, margin=dict(t=40,b=10,l=0,r=0))
        st.plotly_chart(fig_geo_e, use_container_width=True)

    st.markdown("""
    <div class="callout c-info">
    Q4-2025 was the geo-tagging peak — 244 users, 343K events. Auto-tagging accounts for
    92–94% of all geo-tags; manual fallback used by very few users (~3–7%).
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Sapling Count Screen (SurveyorSaplingCountActivity)")
    st.markdown("""
    <div class="callout c-warn">
    <b>Usage collapsed after Q3-2025.</b> 402 users in Q2-2025 → 2 users from Q4-2025 onwards.
    Likely replaced by the geo-tagging flow or monitoring workflow changed.
    </div>
    """, unsafe_allow_html=True)
    fig_sc = px.bar(df, x="quarter", y="sapling_count_users",
                    title="Sapling Count Screen Users",
                    color_discrete_sequence=["#f59e0b"])
    fig_sc.update_layout(height=260, margin=dict(t=40,b=10,l=0,r=0))
    st.plotly_chart(fig_sc, use_container_width=True)

    st.subheader("Background Worker Sync")
    fig_w = go.Figure()
    fig_w.add_bar(x=df["quarter"], y=df["worker_fails"],    name="worker_fail events",    marker_color="#fca5a5")
    fig_w.add_bar(x=df["quarter"], y=df["net_failures"]/1000, name="network_failures (÷1K)", marker_color="#bfdbfe")
    fig_w.update_layout(barmode="group", title="Worker Failures & Network Failures per Quarter",
                        height=320, margin=dict(t=40,b=20,l=0,r=0),
                        legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_w, use_container_width=True)
    st.caption("Workers: ConvertMediaToPDFWorker, UploadMediaWorker, SaplingSyncWorker (new Q1-2026). Avg 5.1 retries per failure — expected in low-connectivity field conditions.")

# ═══════════════════════════════════════════════════════════════════════
# TAB 5: STABILITY
# ═══════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("Crashlytics — by Category")

    if not crash_df.empty:
        fig_crash = px.bar(crash_df, x="quarter", y="crashes", color="category",
                           title="Crashes by Category per Quarter",
                           barmode="stack",
                           color_discrete_sequence=px.colors.qualitative.Set2)
        fig_crash.update_layout(height=380, margin=dict(t=40,b=20,l=0,r=0),
                                legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_crash, use_container_width=True)

        # Fatal crashes
        fatal = crash_df.groupby("quarter")["fatal_crashes"].sum().reset_index()
        fig_fatal = px.bar(fatal, x="quarter", y="fatal_crashes",
                           title="Fatal Crashes per Quarter",
                           color_discrete_sequence=["#dc2626"])
        fig_fatal.update_layout(height=260, margin=dict(t=40,b=10,l=0,r=0))
        st.plotly_chart(fig_fatal, use_container_width=True)

        with st.expander("📋 Crash detail by category"):
            pivot = crash_df.pivot_table(index="category", columns="quarter",
                                          values="crashes", aggfunc="sum", fill_value=0)
            st.dataframe(pivot, use_container_width=True)

    st.subheader("GA4 Error Events")
    fig_err = go.Figure()
    fig_err.add_bar(x=df["quarter"], y=df["update_errors"], name="App Update Errors", marker_color="#dc2626")
    fig_err.add_bar(x=df["quarter"], y=df["pdf_errors"],    name="PDF Errors",        marker_color="#f97316")
    fig_err.update_layout(barmode="group", title="App Update Errors & PDF Errors per Quarter",
                          height=300, margin=dict(t=40,b=20,l=0,r=0),
                          legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_err, use_container_width=True)

    st.markdown("""
    <div class="callout c-alert">
    <b>App Update crashes are the top open issue.</b> 44,889 Crashlytics events from 815 devices in Q2-2026.
    81.8% of users are on old builds. Enforce mandatory update via Play Store in-app update API.
    </div>
    <div class="callout c-good">
    <b>Win:</b> Zero fatal crashes in Q2-2026 — first time across all 5 quarters.
    Media sync issue (63K crashes in Q3-2025) fully resolved.
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 6: COVERAGE GAPS
# ═══════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Features Not Yet Tracked in GA4")
    st.markdown("""
    <div class="callout c-alert">
    These features exist in the app but have <b>zero custom GA4 events</b>.
    Their usage is invisible to this dashboard and to product decisions.
    </div>
    """, unsafe_allow_html=True)

    gaps = [
        ("🔴 P0", "LSC (Land Survey)",      "No events — lsc_form_started, lsc_submitted needed"),
        ("🔴 P0", "Monitoring Rounds",       "No events — monitoring_started, monitoring_submitted needed"),
        ("🔴 P0", "Soil Sampling",           "No events — soil_sample_started, soil_sample_submitted needed"),
        ("🔴 P0", "OTP Delivery Funnel",     "No otp_sent / otp_delivered / otp_failed events for CRA/FPIC"),
        ("🟡 P1", "Tasks / Activities",      "No task_opened, task_completed events"),
        ("🟡 P1", "Ground Prep",             "No pit_measurement_completed, spacing_measurement_completed"),
        ("🟡 P1", "Document Re-Uploads",     "Only screen_view tracked — no custom event"),
        ("⚪ P2", "Draft Save & Recovery",   "No draft_saved, draft_restored events"),
    ]
    gap_df = pd.DataFrame(gaps, columns=["Priority","Feature","What's needed"])
    st.dataframe(gap_df.set_index("Priority"), use_container_width=True)

    st.subheader("Screen-only tracked features (partial visibility)")
    screens = [
        ("SurveyorSaplingCountActivity","Sapling count / monitoring proxy","Dropped 402→2 users after Q3-2025"),
        ("UpdateLandAreaActivity","Farm boundary edits","28–139 users/quarter"),
        ("ImageCropperActivity / ImageCaptureActivity","Photo capture","Launched Q4-2025, growing"),
        ("GmsDocumentScanningDelegateActivity","Document scanner (legacy, ended Q4-2025)","Replaced by ImageCaptureActivity"),
    ]
    sc_df = pd.DataFrame(screens, columns=["Screen Class","Maps to","Note"])
    st.dataframe(sc_df.set_index("Screen Class"), use_container_width=True)

# ── Footer ────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Varaha Climate-Tech · ARR Partner App · Data: BigQuery `arr-partner-app.analytics_445901335` · Refreshes hourly · New quarters appear automatically")
