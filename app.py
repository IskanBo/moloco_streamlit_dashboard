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
    st.title("Dashboard: Затраты на рекламу")
    st.markdown("Добро пожаловать в дашборд мониторинга затрат по источникам трафика.")

    if not st.session_state["loaded"]:
        st.info("Нажмите «Обновить» в боковом меню, чтобы загрузить данные")
        st.stop()

    # --- данные Moloco ---
    df_m = st.session_state["moloco"].copy()
    df_m["event_time"] = pd.to_datetime(df_m["event_time"]).dt.date
    latest   = df_m["event_time"].max()
    prev_day = latest - timedelta(days=1)

    st.info(
        "**Данные отражают расходы за прошедший день** — "
        f"{prev_day:%d %B %Y}.",
        icon="ℹ️",
    )

    # ---------- KPI Moloco ----------
    vals_today  = df_m[df_m["event_time"] == prev_day]["cost"].dropna().astype(str)
    vals_yest   = df_m[df_m["event_time"] == prev_day - timedelta(days=1)]["cost"].dropna().astype(str)

    curr_usd = sum(clean_num(v) for v in vals_today)
    prev_usd = sum(clean_num(v) for v in vals_yest)

    if usd_rate:
        curr_rub = curr_usd * usd_rate
        prev_rub = prev_usd * usd_rate
        delta_pct = (curr_rub - prev_rub) / prev_rub * 100 if prev_rub else 0
        value_moloco = f"{int(curr_rub):,} ₽".replace(",", " ")
    else:
        curr_rub   = None
        delta_pct  = (curr_usd - prev_usd) / prev_usd * 100 if prev_usd else 0
        value_moloco = f"{int(curr_usd):,} $".replace(",", " ")

    delta_text = f"{delta_pct:+.1f}%"
    label_moloco = f"Moloco (≈ ${int(curr_usd):,})".replace(",", " ")

    st.metric(label=label_moloco, value=value_moloco, delta=delta_text)

    # ---------- KPI прочие источники ----------
    df_o = st.session_state["other"].copy()
    df_o["event_time"] = pd.to_datetime(df_o.get("event_date", df_o.get("event_time"))).dt.date

    items = []
    for src, grp in df_o.groupby("traffic_source"):
        cur_val  = sum(clean_num(v) for v in grp[grp["event_time"] == prev_day]["costs"].dropna().astype(str))
        prev_val = sum(clean_num(v) for v in grp[grp["event_time"] == prev_day - timedelta(days=1)]["costs"].dropna().astype(str))
        delta    = (cur_val - prev_val) / prev_val * 100 if prev_val else 0
        items.append((src, cur_val, delta))

    # вывод карточек в две строки
    half = (len(items) + 1) // 2
    for row in [items[:half], items[half:]]:
        cols = st.columns(len(row))
        for (src, total, d), col in zip(row, cols):
            col.metric(
                label=src,
                value=f"{int(total):,} ₽".replace(",", " "),
                delta=f"{d:+.1f}%"
            )

    # делаем все метрики «карточками»
    style_metric_cards(
        background_color="rgba(255,255,255,0.05)",  # лёгкая «дымка», видно на Dark
        border_color="#444444",  # тонкий тёмный бордер
        border_radius_px=12,
        box_shadow=True,
    )

    # ---------- Трендовый график ----------
    st.divider()
    st.header("Тренд затрат по источникам")

    # Moloco в ₽
    moloco_df = df_m.copy()
    moloco_df["cost_rub"] = moloco_df["cost"].apply(clean_num) * (usd_rate or 1)

    mol_daily = (
        moloco_df.groupby("event_time")["cost_rub"]
        .sum().reset_index().assign(traffic_source="Moloco")
    )

    # Другие источники (и так ₽)
    df_o["cost_num"] = df_o["costs"].apply(clean_num)
    other_daily = (
        df_o.groupby(["event_time", "traffic_source"])["cost_num"]
        .sum().reset_index().rename(columns={"cost_num": "cost_rub"})
    )

    chart_df = pd.concat([mol_daily, other_daily], ignore_index=True)

    sources = chart_df["traffic_source"].unique().tolist()
    default_sel = ["Moloco"]
    visible = st.multiselect("Источники на графике", sources, default_sel, key="src_plot")

    data_plot = chart_df[chart_df["traffic_source"].isin(visible)]

    if not data_plot.empty:
        fig = px.line(
            data_plot,
            x="event_time",
            y="cost_rub",
            color="traffic_source",
            labels={"event_time": "Дата", "cost_rub": "Затраты (₽)", "traffic_source": "Источник"},
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )

        fig.update_layout(
            xaxis=dict(
                rangeselector=dict(
                    buttons=[
                        dict(count=7, label="Неделя", step="day", stepmode="backward"),
                        dict(count=1, label="Месяц", step="month", stepmode="backward"),
                        dict(step="all", label="Весь период")
                    ]
                ),
                rangeslider=dict(visible=True),
                type="date",
            ),
            yaxis=dict(tickformat=",.0f"),
        )
        fig.update_traces(marker=dict(size=4), line=dict(width=2))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Выберите хотя бы один источник для отображения графика.")

# -----------------------------------------------------------------
#  Остальные вкладки-п заглушки
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
