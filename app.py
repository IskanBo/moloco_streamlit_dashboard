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
menu = st.sidebar.radio("", ["Главная", "Диаграммы", "Сводные таблицы", "Табличные данные"])
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

    # Moloco
    moloco_usd       = df_m.loc[df_m["event_time"] == prev_day, "cost"].map(clean_num).sum()
    moloco_usd_prev  = df_m.loc[df_m["event_time"] == prev_day - timedelta(days=1), "cost"].map(clean_num).sum()
    moloco_rub       = moloco_usd * usd_rate if usd_rate else None
    moloco_rub_prev  = moloco_usd_prev * usd_rate if usd_rate else None
    delta_moloco_pct = ((moloco_rub - moloco_rub_prev) / moloco_rub_prev * 100) if moloco_rub_prev else 0

    st.markdown(
        f"""
        <div style="border:1px solid #505050;border-radius:8px;padding:18px 20px 22px 20px;margin-bottom:22px;">
          <div style="font-size:15px;color:#a0a0a0;margin-bottom:4px;">Moloco</div>
          <div style="font-size:40px;font-weight:600;line-height:1.15;">
              {int(moloco_rub):,}&nbsp;₽
              <span style="font-size:15px;color:#b0b0b0;">≈ ${moloco_usd:,.0f}</span>
          </div>
          <div style="color:{'limegreen' if delta_moloco_pct>=0 else 'orangered'};font-size:18px;margin-top:4px;">
              {delta_moloco_pct:+.1f}%
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Other sources
    df_o = st.session_state["other"].copy()
    df_o.columns = (
        df_o.columns.str.replace(r"\s+", "", regex=True).str.lower()
    )
    df_o["event_time"] = pd.to_datetime(df_o["event_date"]).dt.date

    cards = []
    for src, grp in df_o.groupby("traffic_source"):
        rub_today = grp.loc[grp["event_time"] == prev_day, "costs"].map(clean_num).sum()
        rub_prev  = grp.loc[grp["event_time"] == prev_day - timedelta(days=1), "costs"].map(clean_num).sum()
        usd_today = rub_today / usd_rate if usd_rate else 0
        delta_pct = ((rub_today - rub_prev) / rub_prev * 100) if rub_prev else 0
        cards.append((src, rub_today, usd_today, delta_pct))

    row_cols = st.columns(3, gap="large")
    for i, (src, rub, usd, dlt) in enumerate(cards):
        with row_cols[i % 3]:
            st.markdown(
                f"""
                <div style="border:1px solid #505050;border-radius:8px;padding:14px 18px 18px 18px;margin-bottom:18px;">
                  <div style="font-size:14px;color:#a0a0a0;margin-bottom:4px;">{src}</div>
                  <div style="font-size:28px;font-weight:600;line-height:1.15;">
                      {int(rub):,}&nbsp;₽
                      <span style="font-size:12px;color:#b0b0b0;">≈ ${usd:,.0f}</span>
                  </div>
                  <div style="color:{'limegreen' if dlt>=0 else 'orangered'};font-size:13px;margin-top:2px;">
                      {dlt:+.1f}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if (i % 3) == 2 and i != len(cards) - 1:
            row_cols = st.columns(3, gap="large")

    # ────────────────────────────────────────────────────────────────
    #  Тренд‑график
    # ────────────────────────────────────────────────────────────────
    st.divider()
    st.header("Тренд затрат по источникам")

    # --- подготовка данных ---
    moloco_df = df_m.copy()
    moloco_df["cost_usd"] = moloco_df["cost"].map(clean_num)
    moloco_df["cost_rub"] = moloco_df["cost_usd"] * usd_rate if usd_rate else float("nan")
    moloco_daily = (
        moloco_df.groupby("event_time")["cost_rub"].sum().reset_index()
        .assign(traffic_source="Moloco")
    )

    df_o["cost_rub"] = df_o["costs"].map(clean_num)
    other_daily = (
        df_o.groupby(["event_time", "traffic_source"])["cost_rub"].sum().reset_index()
    )

    chart_df = pd.concat([moloco_daily, other_daily], ignore_index=True)

    # ---------- НОВЫЙ БЛОК: убираем неполный последний день ----------
    latest_dt = chart_df["event_time"].max()
    chart_df = chart_df[chart_df["event_time"] < latest_dt]
    # ---------------------------------------------------------------

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


    # ────────────────────────────────────────────────────────────────
    #  TOP‑10 Bayer id (Moloco vs. другие источники)
    # ────────────────────────────────────────────────────────────────

    @st.cache_data(show_spinner=False)
    def _prepare_bayer_dfs(df_m: pd.DataFrame, df_o: pd.DataFrame, usd_rate: float) -> tuple[
        pd.DataFrame, pd.DataFrame]:
        """Готовит датафреймы с затратами в рублях и единым названием колонки `bayer_id`."""
        # --- Moloco ---
        moloco = df_m.copy()
        moloco.rename(columns={"Bayer id": "bayer_id"}, inplace=True)  # унифицируем название
        moloco["event_time"] = pd.to_datetime(moloco["event_time"]).dt.date
        moloco["cost_rub"] = moloco["cost"].map(clean_num) * usd_rate

        # --- Other ---
        other = df_o.copy()
        other.columns = other.columns.str.replace(r"\s+", "", regex=True).str.lower()
        other.rename(columns={"bayerid": "bayer_id"}, inplace=True)
        dt_col = "event_date" if "event_date" in other.columns else "event_time"
        other[dt_col] = pd.to_datetime(other[dt_col]).dt.date
        other["event_time"] = other[dt_col]  # приводим к единому названию
        other["cost_rub"] = other["costs"].map(clean_num)

        return moloco, other


    def _build_top10_moloco(df: pd.DataFrame, start: date, end: date) -> px.bar:
        """Горизонтальный бар‑чарт TOP‑10 Bayer из Moloco."""
        mask = (df["event_time"] >= start) & (df["event_time"] <= end)
        top10 = (
            df.loc[mask]
            .groupby("bayer_id", as_index=False)["cost_rub"].sum()
            .nlargest(10, "cost_rub")
            .sort_values("cost_rub")  # снизу – самый дорогой
        )
        fig = px.bar(
            top10,
            x="cost_rub",
            y="bayer_id",
            orientation="h",
            labels=dict(cost_rub="Затраты (₽)", bayer_id="Bayer id"),
        )
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_layout(showlegend=False, title_text="Moloco • TOP‑10 Bayer id")
        return fig


    def _build_top10_other(df: pd.DataFrame, start: date, end: date, sources: list[str]) -> px.bar:
        """Горизонтальный накопительный бар‑чарт TOP‑10 Bayer для выбранных источников."""
        mask = (df["event_time"] >= start) & (df["event_time"] <= end) & (df["traffic_source"].isin(sources))
        # агрегируем по Bayer‑id + source
        agg = (
            df.loc[mask]
            .groupby(["bayer_id", "traffic_source"], as_index=False)["cost_rub"].sum()
        )
        # выбираем TOP‑10 Bayer по суммарным затратам
        tot = agg.groupby("bayer_id", as_index=False)["cost_rub"].sum()
        top_ids = tot.nlargest(10, "cost_rub")["bayer_id"]
        top_df = agg[agg["bayer_id"].isin(top_ids)].sort_values("cost_rub")
        fig = px.bar(
            top_df,
            x="cost_rub",
            y="bayer_id",
            color="traffic_source",
            orientation="h",
            labels=dict(cost_rub="Затраты (₽)", bayer_id="Bayer id", traffic_source="Источник"),
            title="Другие источники • TOP‑10 Bayer id",
        )
        fig.update_yaxes(categoryorder="total ascending")
        return fig


    # ---------- подготовка данных ----------
    moloco_all, other_all = _prepare_bayer_dfs(df_m, df_o, usd_rate)

    # диапазон дат (общий минимум/максимум для обеих таблиц)
    global_min = min(moloco_all["event_time"].min(), other_all["event_time"].min())
    global_max = max(moloco_all["event_time"].max(), other_all["event_time"].max())

    st.divider()  # отделяем от тренд‑графика
    st.header("TOP‑10 Bayer id по затратам")

    # ── выбор дат ───────────────────────────────────────────────────
    col_d1, col_d2 = st.columns(2, gap="medium")
    with col_d1:
        d_start = st.date_input("Начало периода", global_min, key="top_bayer_start")
    with col_d2:
        d_end = st.date_input("Конец периода", global_max, key="top_bayer_end")

    if d_start > d_end:
        st.error("❌ Начальная дата позже конечной")
        st.stop()

    # ── выбор источников для правого графика ────────────────────────
    other_sources_all = sorted(other_all["traffic_source"].unique())
    sel_other_sources = st.multiselect(
        "Источники в правом графике",
        options=other_sources_all,
        default=other_sources_all,
        key="sel_other_sources",
    )

    if not sel_other_sources:
        st.warning("Выберите хотя бы один источник для правого графика")
        st.stop()

    # ── сами графики ────────────────────────────────────────────────
    c1, c2 = st.columns(2, gap="large")
    with c1:
        fig_left = _build_top10_moloco(moloco_all, d_start, d_end)
        st.plotly_chart(fig_left, use_container_width=True)

    with c2:
        fig_right = _build_top10_other(other_all, d_start, d_end, sel_other_sources)
        st.plotly_chart(fig_right, use_container_width=True)

# -----------------------------------------------------------------
#  Остальные вкладки-заглушки
# -----------------------------------------------------------------

elif menu == "Диаграммы":
    st.header("Диаграммы")
    st.info("В разработке")

elif menu == "Сводные таблицы":
    st.header("Сводные таблицы")
    st.info("В разработке")

# -----------------------------------------------------------------
#  Табличные данные: просмотр и фильтр по дате
# -----------------------------------------------------------------
elif menu == "Табличные данные":
    st.title("Табличные данные из Google Sheets")

    if not st.session_state["loaded"]:
        st.info("Нажмите «Обновить» в боковом меню для загрузки данных")
        st.stop()

    # ── 1) Moloco ────────────────────────────────────────────────
    st.subheader("Moloco")
    df_moloco = st.session_state["moloco"].copy()
    df_moloco["event_time"] = pd.to_datetime(df_moloco["event_time"]).dt.date

    col1, col2 = st.columns(2)
    with col1:
        min_m, max_m = df_moloco["event_time"].min(), df_moloco["event_time"].max()
        start_m = st.date_input("Начало периода", min_m, key="moloco_start")
    with col2:
        end_m = st.date_input("Конец периода", max_m, key="moloco_end")

    mask_m = (df_moloco["event_time"] >= start_m) & (df_moloco["event_time"] <= end_m)
    st.dataframe(df_moloco.loc[mask_m])

    # ── 2) Other sources ─────────────────────────────────────────
    st.subheader("Other sources")
    df_other = st.session_state["other"].copy()
    # В разных таблицах колонка может называться event_date или event_time
    dt_col = "event_date" if "event_date" in df_other.columns else "event_time"
    df_other[dt_col] = pd.to_datetime(df_other[dt_col]).dt.date

    col3, col4 = st.columns(2)
    with col3:
        min_o, max_o = df_other[dt_col].min(), df_other[dt_col].max()
        start_o = st.date_input("Начало периода ", min_o, key="other_start")
    with col4:
        end_o = st.date_input("Конец периода ", max_o, key="other_end")

    mask_o = (df_other[dt_col] >= start_o) & (df_other[dt_col] <= end_o)
    st.dataframe(df_other.loc[mask_o])

