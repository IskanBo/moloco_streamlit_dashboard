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
MOLOCO_SHEET_ID = st.secrets["MOLOCO_SHEET_ID"]
OTHER_SOURCES_SHEET_ID = st.secrets["OTHER_SOURCES_SHEET_ID"]
DASHBOARD_PASSWORD = st.secrets["DASHBOARD_PASSWORD"]

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
# Утилиты
# ----------------------------------------
def clean_num(s: str) -> float:
    t = re.sub(r"\s+", "", s)
    return float(t.replace(',', '.'))

# ----------------------------------------
# Загрузка данных
# ----------------------------------------
@st.cache_data(show_spinner=False)
def fetch_moloco_raw():
    sh = client.open_by_key(MOLOCO_SHEET_ID)
    rows = []
    for ws in sh.worksheets():
        vals = ws.get_all_values()
        header = vals[0]
        for r in vals[1:]: rows.append(dict(zip(header, r)))
    df = pd.DataFrame(rows)
    if not df.empty: df['traffic_source'] = 'Moloco'
    return df

@st.cache_data(show_spinner=False)
def fetch_other_raw():
    sh = client.open_by_key(OTHER_SOURCES_SHEET_ID)
    vals = sh.get_worksheet(0).get_all_values()
    header = vals[0]
    df = pd.DataFrame(vals[1:], columns=header)
    if 'traffic_source' not in df.columns: df['traffic_source'] = 'Other'
    return df

@st.cache_data(ttl=3600)
def get_rates():
    try:
        rates = ExchangeRates(date.today())
        return rates['USD'].value, rates['EUR'].value
    except:
        return None, None

# ----------------------------------------
# Сессия
# ----------------------------------------
for key in ('moloco','other'):
    if key not in st.session_state: st.session_state[key] = pd.DataFrame()
if 'loaded' not in st.session_state: st.session_state['loaded'] = False
if 'last_update' not in st.session_state: st.session_state['last_update'] = None

# ----------------------------------------
# Sidebar
# ----------------------------------------
st.sidebar.title('Навигация')
menu = st.sidebar.radio('', ['Главная','Диаграммы','Сводные таблицы','Сырые данные'])
st.sidebar.markdown('---')
usd_rate, eur_rate = get_rates()
st.sidebar.caption(f'USD/RUB: {usd_rate:.2f}' if usd_rate else 'USD/RUB: —')
st.sidebar.caption(f'EUR/RUB: {eur_rate:.2f}' if eur_rate else 'EUR/RUB: —')
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
# Main
# ----------------------------------------
if menu == 'Главная':
    st.title('Dashboard: Затраты рекламы')
    st.markdown('Добро пожаловать в дашборд управления затратами по рекламным кампаниям.')
    if not st.session_state['loaded']:
        st.info('Нажмите «Обновить» в меню, чтобы загрузить данные')
    else:
        df_m = st.session_state['moloco'].copy()
        df_m['event_time'] = pd.to_datetime(df_m['event_time']).dt.date
        latest = df_m['event_time'].max()
        prev_day = latest - timedelta(days=1)
        st.markdown(f"**Дата:** {prev_day}")

        # Moloco KPI (более крупный блок)
        vals = df_m[df_m['event_time']==prev_day]['cost']
        curr_usd = sum(clean_num(v) for v in vals)
        curr_rub = curr_usd * usd_rate if usd_rate is not None else None
                prev_vals = df_m[df_m['event_time']==prev_day-timedelta(days=1)]['cost']
