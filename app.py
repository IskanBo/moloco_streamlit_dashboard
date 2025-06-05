import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta, date
import pytz
from pycbrf.toolbox import ExchangeRates
import plotly.express as px
import re
from streamlit_extras.metric_cards import style_metric_cards

# ────────────────────────────────────────────────────────────────
#  Секреты (берём из Streamlit Cloud или .env при локальной работе)
# ────────────────────────────────────────────────────────────────
creds = st.secrets["google_service_account"]
client = gspread.service_account_from_dict(creds)

MOLOCO_SHEET_ID        = st.secrets["MOLOCO_SHEET_ID"]
OTHER_SOURCES_SHEET_ID = st.secrets["OTHER_SOURCES_SHEET_ID"]
DASHBOARD_PASSWORD     = st.secrets["DASHBOARD_PASSWORD"]

# ────────────────────────────────────────────────────────────────
#  Авторизация
# ────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pwd = st.sidebar.text_input("Пароль", type="password", key="login_input")
    if pwd and pwd == DASHBOARD_PASSWORD:
        st.session_state.authenticated = True
    else:
        st.stop()
else:
    st.sidebar.success("Вы авторизованы")

# ────────────────────────────────────────────────────────────────
#  Вспомогательные функции
# ────────────────────────────────────────────────────────────────
def clean_num(s: str) -> float:
    t = re.sub(r"\s+", "", s)
    return float(t.replace(",", "."))

@st.cache_data(show_spinner=False)
def fetch_moloco_raw():
    sh = client.open_by_key(MOLOCO_SHEET_ID)
    rows = []
    for ws in sh.worksheets():
        vals = ws.get_all_values()
        header = vals[0]
        rows.extend(dict(zip(header, r)) for r in vals[1:])
    df = pd.DataFrame(rows)
    if not df.empty:
        df["traffic_source"] = "Moloco"
    return df

@st.cache_data(show_spinner=False)
def fetch_other_raw():
    sh = client.open_by_key(OTHER_SOURCES_SHEET_ID)
    vals = sh.get_worksheet(0).get_all_values()
    header = vals[0]
    df = pd.DataFrame(vals[1:], columns=header)
    if "traffic_source" not in df.columns:
        df["traffic_source"] = "Other"
    return df

@st.cache_data(ttl=3600)
def get_rates():
    try:
        rates = ExchangeRates(date.today())
        return float(rates["USD"].value), float(rates["EUR"].value)
    except Exception:
        return None, None

# ────────────────────────────────────────────────────────────────
#  State
# ────────────────────────────────────────────────────────────────
for key in ("moloco", "other"):
    st.session_state.setdefault(key, pd.DataFrame())
st.session_state.setdefault("loaded", False)
st.session_state.setdefault("last_update", None)

# ────────────────────────────────────────────────────────────────
#  Sidebar
# ────────────────────────────────────────────────────────────────
st.sidebar.title("Навигация")
menu = st.sidebar.radio("", ["Главная", "Диаграммы", "Сводные таблицы", "Сырые данные"])
st.sidebar.markdown("---")

usd_rate, eur_rate = get_rates()
st.sidebar.caption(f"USD/RUB: {usd_rate:.2f}" if usd_rate else "USD/RUB: —")
st.sidebar.caption(f"EUR/RUB: {eur_rate:.2f}" if eur_rate else "EUR/RUB: —")
st.sidebar.markdown("---")

if st.sidebar.button("Обновить"):
    st.session_state["moloco"] = fetch_moloco_raw()
    st.session_state["other"] = fetch_other_raw()
    st.session_state["loaded"] = True
    st.session_state["last_update"] = datetime.now(pytz.timezone("Europe/Moscow"))

if ts := st.session_state["last_update"]:
    st.sidebar.caption(ts.strftime("Обновлено: %Y-%m-%d %H:%M"))
st.sidebar.caption("✅ Данные загружены" if st.session_state["loaded"] else "❌ Данные не загружены")

# ────────────────────────────────────────────────────────────────
#  Главная
# ────────────────────────────────────────────────────────────────
if menu == "Главная":
    st.title("Dashboard: Затраты рекламы")
    st.markdown(
        "Добро пожаловать в дашборд мониторинга затрат по источникам трафика."
    )

    if not st.session_state["loaded"]:
        st.info("Нажмите «Обновить» в боковом меню, чтобы загрузить данные")
        st.stop()

    # ---------- дата отчёта и информационный баннер ----------
    df_m = st.session_state["moloco"].copy()
    df_m["event_time"] = pd.to_datetime(df_m["event_time"]).dt.date
    latest  = df_m["event_time"].max()
    prev_day = latest - timedelta(days=1)

    st.info(
        f"Данные отражают **расходы за прошедший день** — {prev_day:%d %B %Y}.",
        icon="ℹ️",
    )


    # ======================================================================
    #                          KPI-карточки
    # ======================================================================

    # ► Moloco затраты
    # ------------------------------------------------------------------
    moloco_usd = df_m.loc[df_m["event_time"] == prev_day, "cost"].map(clean_num).sum()
    moloco_usd_prev = df_m.loc[df_m["event_time"] == prev_day - timedelta(days=1), "cost"].map(clean_num).sum()
    moloco_rub = moloco_usd * usd_rate if usd_rate else None
    moloco_rub_prev = moloco_usd_prev * usd_rate if usd_rate else None
    delta_pct_moloco = ((moloco_rub - moloco_rub_prev) / moloco_rub_prev * 100) if moloco_rub_prev else 0

    with st.container():
        st.markdown(
            f"""
            <div style="
                 border:1px solid #444;
                 border-radius:8px;
                 padding:18px 22px;
                 margin-bottom:18px;
                 ">
              <div style="font-size:15px;color:gray;">Moloco</div>
              <div style="font-size:38px;font-weight:600;">
                  {int(moloco_rub):,}&nbsp;₽
                  <span style="font-size:14px;color:#A0A0A0;">≈ ${moloco_usd:,.0f}</span>
              </div>
              <div style="color:{'limegreen' if delta_pct_moloco >= 0 else 'orangered'};
                          font-size:18px;">
                  {delta_pct_moloco:+.1f}%
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ► Other sources
    # ------------------------------------------------------------------
    df_o = st.session_state["other"].copy()
    df_o["event_time"] = pd.to_datetime(
        df_o.get("event_date", df_o.get("event_time"))
    ).dt.date

    cards = []
    for src, grp in df_o.groupby("traffic_source"):
        rub_today = grp.loc[grp["event_time"] == prev_day, "costs"].map(clean_num).sum()
        rub_prev = grp.loc[grp["event_time"] == prev_day - timedelta(days=1), "costs"].map(clean_num).sum()
        usd_today = rub_today / usd_rate if usd_rate else None
        delta_pct = ((rub_today - rub_prev) / rub_prev * 100) if rub_prev else 0
        cards.append((src, rub_today, usd_today, delta_pct))

    cols = st.columns(3, gap="large")
    for idx, (src, rub, usd, dlt) in enumerate(cards):
        with cols[idx % 3]:
            st.markdown(
                f"""
                <div style="
                     border:1px solid #444;
                     border-radius:8px;
                     padding:16px 20px;
                     margin-bottom:18px;
                     text-align:center;">
                  <div style="font-size:14px;color:gray;">{src}</div>
                  <div style="font-size:28px;font-weight:600;">
                      {int(rub):,}&nbsp;₽
                      <span style="font-size:12px;color:#A0A0A0;">≈ ${usd:,.0f}</span>
                  </div>
                  <div style="color:{'limegreen' if dlt >= 0 else 'orangered'};
                              font-size:13px;">
                      {dlt:+.1f}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if (idx % 3) == 2 and idx != len(cards) - 1:
            cols = st.columns(3, gap="large")

    # ======================================================================
    #                       Тренд-график
    # ======================================================================
    st.divider()
    st.header("Тренд затрат по источникам")

    # --- подготовка данных ---
    moloco_df = df_m.copy()
    moloco_df["cost_usd"] = moloco_df["cost"].map(clean_num)
    moloco_df["cost_rub"] = moloco_df["cost_usd"] * usd_rate if usd_rate else float("nan")
    moloco_daily = (
        moloco_df.groupby("event_time")["cost_rub"].sum().reset_index().assign(traffic_source="Moloco")
    )

    df_o["cost_rub"] = df_o["costs"].map(clean_num)
    other_daily = (
        df_o.groupby(["event_time", "traffic_source"])["cost_rub"].sum().reset_index()
    )

    chart_df = pd.concat([moloco_daily, other_daily], ignore_index=True)

    # --- фильтр источников ---
    sources_all = chart_df["traffic_source"].unique().tolist()
    sel_sources = st.multiselect(
        "Источники на графике",
        options=sources_all,
        default=["Moloco"],
        key="sel_sources_chart",
    )
    if not sel_sources:
        st.warning("Выберите хотя бы один источник")
        st.stop()

    chart_df = chart_df[chart_df["traffic_source"].isin(sel_sources)]

    # --- построение ---
    fig = px.line(
        chart_df,
        x="event_time",
        y="cost_rub",
        color="traffic_source",
        labels=dict(event_time="Дата", cost_rub="Затраты (₽)", traffic_source="Источник"),
    )
    fig.update_layout(colorway=px.colors.qualitative.Pastel)
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="Неделя", step="day", stepmode="backward"),
                    dict(count=1, label="Месяц", step="month", stepmode="backward"),
                    dict(step="all", label="Всё"),
                ]
            ),
            rangeslider=dict(visible=True),
            type="date",
        )
    )
    fig.update_traces(marker=dict(size=4), line=dict(width=2))
    fig.update_yaxes(tickformat=",.0f")

    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------
#  Остальные вкладки-заглушки
# -----------------------------------------------------------------

elif menu == "Диаграммы":
    st.header("Диаграммы")
    st.info("В разработке")

elif menu == "Сводные таблицы":
    st.header("Сводные таблицы")
    st.info("В разработке")

elif menu == "Сырые данные":
    st.title("Сырые данные из Google Sheets")
    if not st.session_state["loaded"]:
        st.info("Нажмите «Обновить» в боковом меню")
    else:
        st.subheader("Moloco Raw")
        st.dataframe(st.session_state["moloco"])
        st.subheader("Other Raw")
        st.dataframe(st.session_state["other"])
