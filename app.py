import streamlit as st
import pandas as pd
import gspread
import json
from datetime import datetime, timedelta, date
import pytz
from pycbrf.toolbox import ExchangeRates
import plotly.express as px
import re

# ----------------------------------------
# Загрузка секретов из Streamlit
# ----------------------------------------
creds = st.secrets["google_service_account"]
client = gspread.service_account_from_dict(creds)

# Остальные переменные из секрета
MOLOCO_SHEET_ID        = st.secrets["MOLOCO_SHEET_ID"]
OTHER_SOURCES_SHEET_ID = st.secrets["OTHER_SOURCES_SHEET_ID"]
DASHBOARD_PASSWORD     = st.secrets["DASHBOARD_PASSWORD"]

# ----------------------------------------
# Авторизация через session_state
# ----------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pwd = st.sidebar.text_input("Пароль", type="password", key="login_input")
    if pwd:
        if pwd == DASHBOARD_PASSWORD:
            st.session_state.authenticated = True
        else:
            st.sidebar.error("Неверный пароль")
            st.stop()
    else:
        st.stop()
else:
    st.sidebar.success("Вы авторизованы")

# ----------------------------------------
# Утилиты для предобработки строки
# ----------------------------------------
def clean_num(s: str) -> float:
    """
    Убирает пробельные символы и конвертирует строку с запятой в float
    """
    t = re.sub(r"\s+", "", s)
    return float(t.replace(",", "."))

# ----------------------------------------
# Функции загрузки данных
# ----------------------------------------
@st.cache_data(show_spinner=False)
def fetch_moloco_raw():
    sh = client.open_by_key(MOLOCO_SHEET_ID)
    rows = []
    for ws in sh.worksheets():
        vals = ws.get_all_values()
        header = vals[0]
        for r in vals[1:]:
            rows.append(dict(zip(header, r)))
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
        return rates["USD"].value, rates["EUR"].value
    except Exception:
        return None, None

# ----------------------------------------
# Инициализация состояния
# ----------------------------------------
for key in ("moloco", "other"):
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame()
if "loaded" not in st.session_state:
    st.session_state["loaded"] = False
if "last_update" not in st.session_state:
    st.session_state["last_update"] = None

# ----------------------------------------
# Боковое меню и курсы валют
# ----------------------------------------
st.sidebar.title("Навигация")
menu = st.sidebar.radio("", ["Главная", "Диаграммы", "Сводные таблицы", "Сырые данные"])
st.sidebar.markdown("---")

usd_rate, eur_rate = get_rates()
st.sidebar.caption(f"USD/RUB: {usd_rate:.2f}" if usd_rate is not None else "USD/RUB: —")
st.sidebar.caption(f"EUR/RUB: {eur_rate:.2f}" if eur_rate is not None else "EUR/RUB: —")
st.sidebar.markdown("---")

if st.sidebar.button("Обновить"):
    st.session_state["moloco"] = fetch_moloco_raw()
    st.session_state["other"] = fetch_other_raw()
    st.session_state["loaded"] = True
    st.session_state["last_update"] = datetime.now(pytz.timezone("Europe/Moscow"))

if st.session_state["last_update"]:
    st.sidebar.caption(
        st.session_state["last_update"].strftime("Обновлено: %Y-%m-%d %H:%M")
    )
st.sidebar.caption(
    "✅ Данные загружены" if st.session_state["loaded"] else "❌ Данные не загружены"
)

# ----------------------------------------
# Основная часть приложения
# ----------------------------------------
if menu == "Главная":
    st.title("Dashboard: Затраты рекламы")

    # ↓ вставляем новый информ-блок здесь
    st.info(
        "📊 **Этот дашборд предназначен для ежедневного мониторинга затрат по всем рекламным источникам.**  \n"
        f"Данные актуальны **за прошедший день** (то есть за {prev_day:%d %b %Y}).",
        icon="ℹ️",
    )

    st.markdown(
        "Добро пожаловать в дашборд управления затратами по рекламным кампаниям."
    )

        # ----------------------------------------
        # Moloco затраты
        # ----------------------------------------
        # Приводим курс к float (Decimal → float)
        if usd_rate is not None:
            usd_rate = float(usd_rate)
        else:
            usd_rate = None

        # Считаем суммы в долларах для Moloco (фильтруем NaN, приводим к str)
        vals = (
            df_m[df_m["event_time"] == prev_day]["cost"]
            .dropna()
            .astype(str)
        )
        curr_usd = sum(clean_num(v) for v in vals)

        prev_vals = (
            df_m[df_m["event_time"] == prev_day - timedelta(days=1)]["cost"]
            .dropna()
            .astype(str)
        )
        prev_sum_usd = sum(clean_num(v) for v in prev_vals)

        # Конвертируем Moloco в рубли, если курс доступен
        if usd_rate is not None:
            curr_rub = curr_usd * usd_rate
            prev_sum_rub = prev_sum_usd * usd_rate
            delta_pct = (
                (curr_rub - prev_sum_rub) / prev_sum_rub * 100
                if prev_sum_rub
                else 0
            )
        else:
            curr_rub = None
            prev_sum_rub = None
            delta_pct = (
                (curr_usd - prev_sum_usd) / prev_sum_usd * 100
                if prev_sum_usd
                else 0
            )

        # Заголовок Moloco и сразу сумма (без пустой строки)
        st.subheader("Moloco")
        if curr_rub is not None:
            rub_str = f"{int(curr_rub):,}".replace(",", " ")
            usd_str = f"{int(curr_usd):,}".replace(",", " ")
            st.markdown(
                f"<span style='font-size:32px; font-weight:bold'>"
                f"{rub_str}₽<sup style='font-size:16px; color:gray'>${usd_str}</sup>"
                f"</span>",
                unsafe_allow_html=True,
            )
        else:
            usd_only = f"{int(curr_usd):,}".replace(",", " ")
            st.markdown(
                f"<span style='font-size:32px; font-weight:bold'>{usd_only}$</span>",
                unsafe_allow_html=True,
            )

        # Дельта под Moloco
        color = "green" if delta_pct >= 0 else "red"
        st.markdown(
            f"<div style='color:{color}; font-size:20px'>{delta_pct:+.1f}%</div>",
            unsafe_allow_html=True,
        )

        # ----------------------------------------
        # Other sources KPI
        # ----------------------------------------
        df_o = st.session_state["other"].copy()
        df_o["event_time"] = pd.to_datetime(
            df_o.get("event_date", df_o.get("event_time"))
        ).dt.date
        items = []
        for src, grp in df_o.groupby("traffic_source"):
            current_vals = (
                grp[grp["event_time"] == prev_day]["costs"]
                .dropna()
                .astype(str)
            )
            tot = sum(clean_num(v) for v in current_vals)

            prev_vals_o = (
                grp[grp["event_time"] == prev_day - timedelta(days=1)]["costs"]
                .dropna()
                .astype(str)
            )
            prev_sum_o = sum(clean_num(v) for v in prev_vals_o)
            delta_src = (tot - prev_sum_o) / prev_sum_o * 100 if prev_sum_o else 0
            items.append((src, tot, delta_src))

        half = (len(items) + 1) // 2
        for row in [items[:half], items[half:]]:
            cols = st.columns(len(row), gap="small")
            for (src, total, d), col in zip(row, cols):
                # Сначала название, без пробела перед суммой
                rub_str = f"{int(total):,}".replace(",", " ")
                col.markdown(f"**{src}**", unsafe_allow_html=True)
                col.markdown(
                    f"<span style='font-size:24px; font-weight:bold'>{rub_str}₽</span>",
                    unsafe_allow_html=True,
                )
                color_src = "green" if d >= 0 else "red"
                col.markdown(
                    f"<span style='color:{color_src}; font-size:14px'>{d:+.1f}%</span>",
                    unsafe_allow_html=True,
                )

        # ----------------------------------------
        # Тренд затрат по источникам (в ₽)
        # ----------------------------------------
        st.divider()
        st.header("Тренд затрат по источникам (в ₽)")

        # Подготовка Moloco (USD→RUB)
        moloco_df = df_m.copy()
        moloco_df["cost_num_usd"] = moloco_df["cost"].apply(clean_num)
        if usd_rate is not None:
            moloco_df["cost_rub"] = moloco_df["cost_num_usd"] * usd_rate
        else:
            moloco_df["cost_rub"] = float("nan")
        moloco_daily = (
            moloco_df.groupby("event_time")["cost_rub"]
            .sum()
            .reset_index()
            .assign(traffic_source="Moloco")
        )

        # Подготовка Other (в рублях уже)
        other_df = st.session_state["other"].copy()
        other_df["event_time"] = pd.to_datetime(
            other_df.get("event_date", other_df.get("event_time"))
        ).dt.date
        other_df["cost_num"] = other_df["costs"].apply(clean_num)
        other_daily = (
            other_df.groupby(["event_time", "traffic_source"])["cost_num"]
            .sum()
            .reset_index()
            .rename(columns={"cost_num": "cost_rub"})
        )

        # Объединяем Moloco и Other
        chart_df = pd.concat([moloco_daily, other_daily], ignore_index=True)

        # 1) Список всех уникальных источников
        all_sources = chart_df["traffic_source"].unique().tolist()

        # 2) По умолчанию оставляем только Moloco
        default_selection = ["Moloco"] if "Moloco" in all_sources else all_sources

        # 3) Мультiselect для выбора источников
        selected = st.multiselect(
            "Выберите источники для графика",
            options=all_sources,
            default=default_selection,
            key="sel_sources",
        )

        filtered = chart_df[chart_df["traffic_source"].isin(selected)].copy()

        if not filtered.empty:
            # 4) Построение графика с range slider по оси X
            fig = px.line(
                filtered,
                x="event_time",
                y="cost_rub",
                color="traffic_source",
                labels={
                    "event_time": "Дата",
                    "cost_rub": "Затраты (₽)",
                    "traffic_source": "Источник",
                },
            )
            # Добавляем pastel-цвета
            fig.update_layout(colorway=px.colors.qualitative.Pastel)

            # Включаем встроенный range slider и кнопки селектора диапазона
            fig.update_layout(
                xaxis=dict(
                    rangeselector=dict(
                        buttons=list([
                            dict(count=7, label="Неделя", step="day", stepmode="backward"),
                            dict(count=1, label="Месяц", step="month", stepmode="backward"),
                            dict(step="all", label="Всё")
                        ])
                    ),
                    rangeslider=dict(visible=True),
                    type="date"
                )
            )

            # Настраиваем маркеры и толщину линий
            fig.update_traces(marker=dict(size=4), line=dict(width=2))

            # Форматируем ось Y с разделителем тысяч
            fig.update_yaxes(tickformat=",.0f")

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Выберите хотя бы один источник для отображения графика.")

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
