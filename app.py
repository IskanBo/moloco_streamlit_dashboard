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
# Авторизация через query-параметр и session_state
# ----------------------------------------
params = st.query_params
if params.get("auth", ["0"])[0] == "1":
    st.session_state.authenticated = True
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    pwd = st.sidebar.text_input("Пароль", type="password", key="login_input")
    if pwd:
        if pwd == DASHBOARD_PASSWORD:
            st.session_state.authenticated = True
            st.query_params = {"auth": ["1"]}
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
    Убирает пробелы и конвертирует строку с запятой в float
    """
    t = re.sub(r"\s+", "", s)
    return float(t.replace(',', '.'))

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
        df['traffic_source'] = 'Moloco'
    return df

@st.cache_data(show_spinner=False)
def fetch_other_raw():
    sh = client.open_by_key(OTHER_SOURCES_SHEET_ID)
    vals = sh.get_worksheet(0).get_all_values()
    header = vals[0]
    df = pd.DataFrame(vals[1:], columns=header)
    if 'traffic_source' not in df.columns:
        df['traffic_source'] = 'Other'
    return df

@st.cache_data(ttl=3600)
def get_rates():
    try:
        rates = ExchangeRates(date.today())
        return rates['USD'].value, rates['EUR'].value
    except Exception:
        return None, None

# ----------------------------------------
# Инициализация состояния
# ----------------------------------------
for key in ('moloco', 'other'):
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame()
if 'loaded' not in st.session_state:
    st.session_state['loaded'] = False
if 'last_update' not in st.session_state:
    st.session_state['last_update'] = None

# ----------------------------------------
# Боковое меню и курсы валют
# ----------------------------------------
st.sidebar.title('Навигация')
menu = st.sidebar.radio('', ['Главная', 'Диаграммы', 'Сводные таблицы', 'Сырые данные'])
st.sidebar.markdown('---')

usd, eur = get_rates()
st.sidebar.caption(f'USD/RUB: {usd:.2f}' if usd is not None else 'USD/RUB: —')
st.sidebar.caption(f'EUR/RUB: {eur:.2f}' if eur is not None else 'EUR/RUB: —')
st.sidebar.markdown('---')

if st.sidebar.button('Обновить'):
    st.session_state['moloco'] = fetch_moloco_raw()
    st.session_state['other'] = fetch_other_raw()
    st.session_state['loaded'] = True
    st.session_state['last_update'] = datetime.now(pytz.timezone('Europe/Moscow'))

if st.session_state['last_update']:
    st.sidebar.caption(st.session_state['last_update'].strftime('Обновлено: %Y-%m-%d %H:%M'))
st.sidebar.caption('✅ Данные загружены' if st.session_state['loaded'] else '❌ Данные не загружены')

# ----------------------------------------
# Основная часть приложения
# ----------------------------------------
if menu == 'Главная':
    st.title('Dashboard: Затраты рекламы')
    st.markdown('Добро пожаловать в дашборд управления затратами по рекламным кампаниям.')
    if not st.session_state['loaded']:
        st.info('Нажмите «Обновить» в боковом меню, чтобы загрузить данные')
    else:
        df_m = st.session_state['moloco'].copy()
        df_m['event_time'] = pd.to_datetime(df_m['event_time']).dt.date
        latest = df_m['event_time'].max()
        prev_day = latest - timedelta(days=1)
        st.markdown(f"**Дата:** {prev_day}")

        # Moloco KPI
        vals = df_m[df_m['event_time'] == prev_day]['cost']
        curr = sum(clean_num(v) for v in vals)
        prev_vals = df_m[df_m['event_time'] == prev_day - timedelta(days=1)]['cost']
        prev_sum = sum(clean_num(v) for v in prev_vals)
        delta = (curr - prev_sum) / prev_sum * 100 if prev_sum else 0

        col1, = st.columns([1])
        with col1:
            st.subheader('Moloco')
            # Значок $ после цифр
            st.metric('', f'{int(curr):,} $'.replace(',', ' '), delta=f'{delta:+.1f}%')

        # Other sources KPI
        df_o = st.session_state['other'].copy()
        df_o['event_time'] = pd.to_datetime(df_o.get('event_date', df_o.get('event_time'))).dt.date
        items = []
        for src, grp in df_o.groupby('traffic_source'):
            current_vals = grp[grp['event_time'] == prev_day]['costs']
            tot = sum(clean_num(v) for v in current_vals)
            prev_vals_o = grp[grp['event_time'] == prev_day - timedelta(days=1)]['costs']
            prev_sum_o = sum(clean_num(v) for v in prev_vals_o)
            delta_src = (tot - prev_sum_o) / prev_sum_o * 100 if prev_sum_o else 0
            items.append((src, tot, delta_src))

        half = (len(items) + 1) // 2
        for row in [items[:half], items[half:]]:
            cols = st.columns(len(row), gap='small')
            for (src, total, d), col in zip(row, cols):
                col.markdown(f"**{src}**")
                # Значок рубля после цифр
                col.metric('', f'{int(total):,} ₽'.replace(',', ' '), delta=f'{d:+.1f}%')

        st.divider()
        st.header('Тренд затрат Moloco')
        df_chart = df_m.copy()
        df_chart['cost_num'] = df_chart['cost'].apply(clean_num)
        daily = df_chart.groupby('event_time')['cost_num'].sum().reset_index()
        today = datetime.now(pytz.timezone('Europe/Moscow')).date()
        daily = daily[daily['event_time'] < today]
        end = daily['event_time'].max()
        start = end.replace(day=1)
        fig = px.line(
            daily,
            x='event_time',
            y='cost_num',
            labels={'event_time':'Дата', 'cost_num':'Затраты'},
            markers=True
        )
        fig.update_traces(marker=dict(size=4), line=dict(width=2))
        fig.update_layout(
            xaxis=dict(rangeslider=dict(visible=True), range=[start, end], tickformat='%d %b'),
            yaxis=dict(tickformat=',.0f'),
            margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)

elif menu == 'Диаграммы':
    st.header('Диаграммы')
    st.info('В разработке')

elif menu == 'Сводные таблицы':
    st.header('Сводные таблицы')
    st.info('В разработке')

elif menu == 'Сырые данные':
    st.title('Сырые данные из Google Sheets')
    if not st.session_state['loaded']:
        st.info('Нажмите «Обновить» в боковом меню')
    else:
        st.subheader('Moloco Raw')
        st.dataframe(st.session_state['moloco'])
        st.subheader('Other Raw')
        st.dataframe(st.session_state['other'])
