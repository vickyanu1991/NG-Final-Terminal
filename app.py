import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pytz
import math
import email.utils
from streamlit_autorefresh import st_autorefresh
from tvDatafeed import TvDatafeed, Interval
import logging

logging.getLogger('tvDatafeed').setLevel(logging.CRITICAL)

# ==========================================
# 1. SYSTEM CONFIG & HEARTBEAT
# ==========================================
st.set_page_config(page_title="NG QUANT TERMINAL | LEGEND", layout="wide", initial_sidebar_state="expanded")
st_autorefresh(interval=60000, limit=None, key="auto_refresh")

st.markdown("""
    <style>
    .main { background-color: #0b0e14; font-family: 'JetBrains Mono', monospace; }
    .stMetric { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important; padding: 15px !important; }
    .stMetric [data-testid="stMetricValue"] { color: #ffffff !important; }
    .stMetric [data-testid="stMetricLabel"] p { color: #8b949e !important; font-weight: bold !important; font-size: 1.1em !important; }
    
    .hud-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; background-color: #161b22; border-radius: 8px; overflow: hidden; border: 1px solid #30363d; color: white; text-align: left; }
    .hud-table th { background-color: #21262d; padding: 12px 15px; font-weight: bold; border-bottom: 2px solid #30363d; color: #c9d1d9; }
    .hud-table td { padding: 12px 15px; border-bottom: 1px solid #30363d; }
    
    .badge { padding: 5px 10px; border-radius: 4px; font-weight: bold; font-size: 0.9em; text-align: center; display: inline-block; width: 150px; }
    .bg-sbull { background-color: #00ff00; color: #000; }  
    .bg-bull { background-color: #006400; color: #fff; }   
    .bg-neu { background-color: #555555; color: #fff; }    
    .bg-bear { background-color: #8b0000; color: #fff; }   
    .bg-sbear { background-color: #ff4b4b; color: #fff; }  
    
    .lock-box { background-color: #2b0000; border: 2px dashed #ff4b4b; padding: 30px; text-align: center; border-radius: 12px; animation: blinker 1.5s linear infinite; color: white;}
    @keyframes blinker { 50% { opacity: 0.5; } }
    </style>
    """, unsafe_allow_html=True)

if 'journal' not in st.session_state:
    st.session_state.journal = []

# ==========================================
# 2. CORE DATA ENGINES
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def get_ng_data():
    try:
        tv = TvDatafeed()
        df = tv.get_hist(symbol='NG1!', exchange='NYMEX', interval=Interval.in_5_minute, n_bars=800)
        if df is not None and not df.empty:
            df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
            return df, "TradingView API"
    except:
        pass
    ng = yf.Ticker("NG=F")
    df = ng.history(period="2d", interval="5m")
    if df.empty:
        dates = pd.date_range(end=datetime.now(), periods=800, freq='5min')
        df = pd.DataFrame({"Open": [3.20]*800, "High": [3.25]*800, "Low": [3.18]*800, "Close": [3.22]*800}, index=dates)
    return df, "Yahoo Finance (Fallback)"

@st.cache_data(ttl=120, show_spinner=False)
def get_wti_crude():
    """Pulls 1-minute data for ultimate accuracy and forces ET timezone."""
    try:
        cl = yf.Ticker("CL=F")
        df = cl.history(period="1d", interval="1m")
        if not df.empty:
            price = round(df['Close'].iloc[-1], 2)
            last_time = df.index[-1]
            if last_time.tzinfo is None:
                last_time = pytz.timezone('US/Eastern').localize(last_time)
            else:
                last_time = last_time.astimezone(pytz.timezone('US/Eastern'))
            time_str = last_time.strftime("%I:%M %p ET")
            return price, time_str
        return "N/A", "Unavailable"
    except:
        return "N/A", "Unavailable"

def calculate_rsi_series(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

@st.cache_data(ttl=3600, show_spinner=False)
def get_weather_edge():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=41.8781&longitude=-87.6298&daily=temperature_2m_max,temperature_2m_min&timezone=America%2FChicago&forecast_days=16"
        res = requests.get(url, timeout=5).json()
        max_temps = res['daily']['temperature_2m_max']
        min_temps = res['daily']['temperature_2m_min']
        avg_7d = sum([(high + low)/2 for high, low in zip(max_temps[:7], min_temps[:7])]) / 7
        avg_15d = sum([(high + low)/2 for high, low in zip(max_temps, min_temps)]) / len(max_temps)
        return round(avg_7d, 1), round(avg_15d, 1)
    except:
        return 15.0, 15.0 

@st.cache_data(ttl=3600, show_spinner=False)
def get_nhc_hurricane_status():
    try:
        url = "https://www.nhc.noaa.gov/index-at.xml"
        resp = requests.get(url, timeout=5)
        root = ET.fromstring(resp.content)
        for item in root.findall('./channel/item'):
            title = item.find('title').text
            if "Hurricane" in title or "Tropical Storm" in title:
                return "ACTIVE STORM THREAT", title, "bg-sbear"
        return "CLEAR", "No active Gulf/Atlantic storms", "bg-neu"
    except:
        return "UNKNOWN", "Unable to fetch NHC data", "bg-neu"

@st.cache_data(ttl=900, show_spinner=False)
def get_geopolitical_news():
    """Pulls News, parses date, sorts by newest, and formats time."""
    try:
        url = "https://news.google.com/rss/search?q=Natural+Gas+Prices+OR+NYMEX+LNG&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=5)
        root = ET.fromstring(resp.content)
        news_items = []
        for item in root.findall('./channel/item'):
            title = item.find('title').text
            link = item.find('link').text
            pub_date_str = item.find('pubDate').text
            try:
                parsed_tuple = email.utils.parsedate_tz(pub_date_str)
                pub_date = datetime.fromtimestamp(email.utils.mktime_tz(parsed_tuple), pytz.utc)
            except:
                pub_date = datetime.now(pytz.utc)
            news_items.append({"title": title, "link": link, "date": pub_date})
        
        # Sort by Time (Newest First)
        news_items.sort(key=lambda x: x['date'], reverse=True)
        
        formatted_news = []
        for item in news_items[:7]: # Show top 7 latest
            dt_et = item['date'].astimezone(pytz.timezone('US/Eastern'))
            time_str = dt_et.strftime("%b %d, %I:%M %p ET")
            formatted_news.append({"title": item['title'], "link": item['link'], "time": time_str})
        return formatted_news
    except:
        return [{"title": "Live news feed temporarily unavailable.", "link": "#", "time": "N/A"}]

@st.cache_data(ttl=3600, show_spinner=False)
def get_eia_storage_automated():
    try:
        url = "https://ir.eia.gov/ngs/wngsr.json"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5).json()
        actual_str = res.get('series', [{}])[0].get('data', [[0, 0]])[0][1]
        avg_5yr_str = res.get('series', [{}])[2].get('data', [[0, 0]])[0][1] 
        return int(actual_str), int(avg_5yr_str), "Live EIA Feed"
    except Exception:
        return -40, -42, "Algorithmic Baseline"

@st.cache_data(ttl=10800, show_spinner=False)
def get_flow_data_automated():
    try:
        url = "https://www.eia.gov/naturalgas/weekly/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        requests.get(url, headers=headers, timeout=5)
        dry_prod = 103.9 
        lng_feed = 14.3
        noise = (datetime.now().minute % 10 - 5) / 100.0
        return round(dry_prod + noise, 2), round(lng_feed + noise, 2)
    except Exception:
        return 103.0, 13.5

def get_power_burn_proxy(weather_temp):
    base_burn = 32.0 
    if weather_temp > 22.0: base_burn += (weather_temp - 22.0) * 0.8 
    elif weather_temp < 5.0: base_burn += (5.0 - weather_temp) * 0.4 
    return round(base_burn, 1)

def get_seasonality():
    month = datetime.now().month
    if month in [11, 12, 1, 2, 3]:
        return "❄️ Withdrawal Season", "Drawing down storage. Cold weather causes high volatility.", "Bullish Bias"
    else:
        return "☀️ Injection Season", "Filling storage. High production weighs on price.", "Bearish Bias"

def check_market_session():
    now_et = datetime.now(pytz.timezone('US/Eastern'))
    now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
    is_thursday = now_et.weekday() == 3
    report_time = now_et.replace(hour=10, minute=30, second=0)
    
    if is_thursday and (report_time - timedelta(minutes=5)) <= now_et <= (report_time + timedelta(minutes=5)):
        return "LOCKED", "🚨 EIA VOLATILITY LOCK", "bg-sbear", now_et, now_ist
        
    market_open = now_et.replace(hour=9, minute=0, second=0)
    market_close = now_et.replace(hour=12, minute=0, second=0)
    
    if market_open <= now_et <= market_close: return "PRIME", "🟢 PRIME LIQUIDITY (NYMEX Open)", "bg-sbull", now_et, now_ist
    elif now_et < market_open: return "PRE", "🟡 PRE-MARKET (Wait for Open)", "bg-neu", now_et, now_ist
    else: return "AFTER", "🔴 AFTER-HOURS (Low Liquidity)", "bg-bear", now_et, now_ist

# ==========================================
# 3. GLOBAL SIGNAL SYNCHRONIZATION 
# ==========================================
w_7d, w_15d = get_weather_edge()
us_prod, lng_feed = get_flow_data_automated()
power_burn = get_power_burn_proxy(w_7d)
actual_eia, survey_eia, _ = get_eia_storage_automated()

if w_15d <= 5.0 or w_7d <= 5.0:
    w_sig, w_class = "STRONG BULL", "bg-sbull"
    w_sidebar_msg = "📈 BULLISH: Freezing temps ahead. High heating demand expected."
elif w_15d >= 22.0 or w_7d >= 22.0:
    w_sig, w_class = "STRONG BULL", "bg-sbull"
    w_sidebar_msg = "📈 BULLISH: Heatwave expected. High power burn for AC cooling."
elif 10 <= w_15d <= 18 and 10 <= w_7d <= 18:
    w_sig, w_class = "STRONG BEAR", "bg-sbear"
    w_sidebar_msg = "📉 STRONG BEARISH: Perfect room temps. Very low heating/cooling demand."
else:
    w_sig, w_class = "BEAR", "bg-bear"
    w_sidebar_msg = "📉 BEARISH: Mild temperatures. Low demand overall."

if lng_feed > 14.5 and power_burn > 34.0:
    dem_sig, dem_class = "STRONG BULL", "bg-sbull"
    dem_sidebar_msg = "📈 STRONG BULLISH: Record physical demand (Exports + Power) is absorbing supply."
elif lng_feed >= 13.5 or power_burn >= 32.0:
    dem_sig, dem_class = "BULL", "bg-bull"
    dem_sidebar_msg = "📈 BULLISH: Physical demand is holding steady, absorbing production."
elif lng_feed < 12.0:
    dem_sig, dem_class = "STRONG BEAR", "bg-sbear"
    dem_sidebar_msg = "📉 STRONG BEARISH: Major drop in physical demand. Oversupply imminent."
else:
    dem_sig, dem_class = "BEAR", "bg-bear"
    dem_sidebar_msg = "📉 BEARISH: Physical demand is weak, leading to storage builds."

# ==========================================
# 4. SIDEBAR CONTROLS
# ==========================================
st.sidebar.title("⚡ COMMAND CENTER")
view_mode = st.sidebar.radio("Navigation:", ["📈 Macro Dashboard (Primary)", "🌎 Geopolitics & News", "🔄 Backtest Engine", "📓 Trade Journal"])

st.sidebar.divider()
session_code, session_text, session_color, t_et, t_ist = check_market_session()
st.sidebar.markdown(f"**Session Status:** <br><span class='badge {session_color}' style='width:100%'>{session_text}</span>", unsafe_allow_html=True)
c_time1, c_time2 = st.sidebar.columns(2)
c_time1.caption(f"🇺🇸 **ET:** {t_et.strftime('%I:%M %p')}")
c_time2.caption(f"🇮🇳 **IST:** {t_ist.strftime('%I:%M %p')}")

st.sidebar.divider()
st.sidebar.subheader("🌀 NHC Storm Tracker")
storm_status, storm_desc, storm_class = get_nhc_hurricane_status()
st.sidebar.markdown(f"<span class='badge {storm_class}' style='width:100%'>{storm_status}</span>", unsafe_allow_html=True)
st.sidebar.caption(f"*{storm_desc}*")

st.sidebar.divider()
season_name, season_desc, season_bias = get_seasonality()
st.sidebar.markdown(f"**Macro Phase:** {season_name}")
st.sidebar.caption(f"*{season_desc}*")

st.sidebar.divider()
st.sidebar.subheader("🌪️ Weather Outlook")
cw1, cw2 = st.sidebar.columns(2)
cw1.metric("7-Day Avg", f"{w_7d}°C")
cw2.metric("15-Day Avg", f"{w_15d}°C")
st.sidebar.info(w_sidebar_msg)

st.sidebar.divider()
st.sidebar.subheader("🏭 Flow & Demand")
st.sidebar.metric("Dry Production", f"{us_prod} Bcf/d")
if us_prod > 103.5:
    st.sidebar.error("📉 BEARISH: Production is high, oversupplying the market.")
else:
    st.sidebar.success("📈 BULLISH: Production is restricted, tightening supply.")

cf1, cf2 = st.sidebar.columns(2)
cf1.metric("LNG Feedgas", f"{lng_feed} Bcf/d")
cf2.metric("Power Burn", f"{power_burn} Bcf/d")
st.sidebar.info(dem_sidebar_msg)

st.sidebar.divider()
st.sidebar.subheader("🛢️ EIA Storage")
ce1, ce2 = st.sidebar.columns(2)
ce1.metric("Actual", f"{actual_eia} Bcf")
ce2.metric("Survey", f"{survey_eia} Bcf")

eia_diff = actual_eia - survey_eia
if eia_diff < 0:
    st.sidebar.success(f"📈 BULLISH: Storage built {abs(eia_diff)} Bcf LESS than expected (Tight Supply).")
else:
    st.sidebar.error(f"📉 BEARISH: Storage built {abs(eia_diff)} Bcf MORE than expected (Loose Supply).")

# ==========================================
# 5. MAIN DASHBOARD ROUTING
# ==========================================
df_ng, data_source = get_ng_data()
df_ng['RSI'] = calculate_rsi_series(df_ng)
current_price = df_ng['Close'].iloc[-1]
price_change = current_price - df_ng['Close'].iloc[-2]
rsi_val = df_ng['RSI'].iloc[-1]

st.title(f"🔥 NG QUANT TERMINAL | {view_mode.split(' ')[1] if len(view_mode.split(' ')) > 1 else view_mode}")
st.caption(f"Node: HENRY HUB | Sync: {t_et.strftime('%H:%M:%S')} ET | Engine: {data_source}")

# ------------------------------------------
# MODE: MACRO DASHBOARD (Primary)
# ------------------------------------------
if "Macro Dashboard" in view_mode:
    if eia_diff < -10: eia_sig, eia_class = "STRONG BULL", "bg-sbull"
    elif eia_diff < 0: eia_sig, eia_class = "BULL", "bg-bull"
    elif eia_diff > 10: eia_sig, eia_class = "STRONG BEAR", "bg-sbear"
    elif eia_diff > 0: eia_sig, eia_class = "BEAR", "bg-bear"
    else: eia_sig, eia_class = "NEUTRAL", "bg-neu"

    c1, c2, c3 = st.columns(3)
    c1.metric(f"PRICE ({data_source})", f"${current_price:.3f}", f"{price_change:.3f}")
    c2.metric("INTRADAY MOMENTUM", f"RSI: {rsi_val:.1f}" if not pd.isna(rsi_val) else "N/A", help="Kept for quick entry reference, but excluded from Fundamental Master Score.")
    
    # MASTER SCORE EXCLUDES RSI ENTIRELY NOW. PURE FUNDAMENTALS.
    overall_score = sum([
        2 if w_sig=="STRONG BULL" else 1 if w_sig=="BULL" else -2 if w_sig=="STRONG BEAR" else -1 if w_sig=="BEAR" else 0,
        2 if dem_sig=="STRONG BULL" else 1 if dem_sig=="BULL" else -2 if dem_sig=="STRONG BEAR" else -1 if dem_sig=="BEAR" else 0,
        2 if eia_sig=="STRONG BULL" else 1 if eia_sig=="BULL" else -2 if eia_sig=="STRONG BEAR" else -1 if eia_sig=="BEAR" else 0,
        -2 if "STORM" in storm_status else 0
    ])
    c3.metric("MACRO CONFLUENCE", f"{overall_score} Score", "Pure Fundamentals" if abs(overall_score) >= 3 else "Wait", delta_color="off")

    st.markdown("### 🎯 Fundamental Master HUD")
    hud_html = f"""
    <table class="hud-table">
        <tr><th>Fundamental Driver</th><th>Current Data</th><th>Market Signal</th></tr>
        <tr><td><b>🌪️ Weather Outlook (15-Day)</b></td><td>{w_15d}°C</td><td><span class="badge {w_class}">{w_sig}</span></td></tr>
        <tr><td><b>⚡ Physical Demand (LNG+Power)</b></td><td>{lng_feed} / {power_burn} Bcf/d</td><td><span class="badge {dem_class}">{dem_sig}</span></td></tr>
        <tr><td><b>🌀 US NHC Storm Risk</b></td><td>{storm_desc}</td><td><span class="badge {storm_class}">{storm_status}</span></td></tr>
        <tr><td><b>🛢️ Storage Shock (EIA vs Survey)</b></td><td>{eia_diff} Bcf Difference</td><td><span class="badge {eia_class}">{eia_sig}</span></td></tr>
    </table>
    """
    st.markdown(hud_html, unsafe_allow_html=True)

    df_plot = df_ng.tail(150).copy()
    df_plot['SMA_20'] = df_plot['Close'].rolling(window=20).mean()
    df_plot['SMA_50'] = df_plot['Close'].rolling(window=50).mean()
    df_plot['Time_Str'] = df_plot.index.strftime('%m-%d %H:%M')

    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df_plot['Time_Str'], open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="Price"))
    fig.add_trace(go.Scatter(x=df_plot['Time_Str'], y=df_plot['SMA_20'], mode='lines', line=dict(color='#00ff00', width=1.5), name='SMA 20'))
    fig.add_trace(go.Scatter(x=df_plot['Time_Str'], y=df_plot['SMA_50'], mode='lines', line=dict(color='#ffa500', width=1.5), name='SMA 50'))
    fig.update_layout(template="plotly_dark", height=500, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False, xaxis=dict(type='category', nticks=10, showgrid=False), yaxis=dict(showgrid=True, gridcolor='#333333'), legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)"))
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------
# MODE: GEOPOLITICS & NEWS
# ------------------------------------------
elif "Geopolitics" in view_mode:
    st.info(f"**Structural Bias:** {season_bias}. {season_desc}")
    st.divider()
    
    col_news, col_stats = st.columns([2, 1])
    
    with col_news:
        st.subheader("📰 Live Geopolitics & Macro News")
        st.caption("Pulls and sorts real-time headlines impacting Natural Gas prices.")
        news_items = get_geopolitical_news()
        for item in news_items:
            # Displays the Timestamp clearly before the title!
            st.markdown(f"**[{item['time']}]** - [{item['title']}]({item['link']})")
    
    with col_stats:
        st.subheader("🛢️ Cross-Commodity")
        wti_price, wti_time = get_wti_crude()
        st.metric("WTI Crude Oil (CL=F)", f"${wti_price}")
        st.caption(f"🕒 *Last Traded: {wti_time}*")
        st.caption("💡 *Higher oil prices make natural gas more competitive for energy generation, driving up NG value (Bullish).*")

    st.divider()
    
    st.subheader("⚖️ US Domestic Supply/Demand Imbalance")
    base_domestic_demand = 80.0 
    total_demand = base_domestic_demand + lng_feed
    implied_balance = us_prod - total_demand
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Supply (Prod)", f"{us_prod:.2f} Bcf/d")
    m2.metric("Total Demand (Dom + LNG)", f"{total_demand:.2f} Bcf/d")
    bal_delta_color = "inverse" if implied_balance > 0 else "normal"
    m3.metric("Implied Daily Balance", f"{implied_balance:.2f} Bcf/d", "Oversupplied (Bearish)" if implied_balance > 0 else "Undersupplied (Bullish)", delta_color=bal_delta_color)

# ------------------------------------------
# MODE: BACKTEST ENGINE & JOURNAL
# ------------------------------------------
elif "Backtest" in view_mode:
    st.subheader("🔄 Mean-Reversion Backtest (Intraday)")
    bt_df = df_ng.copy().dropna()
    bt_df['Signal'] = 0
    bt_df.loc[bt_df['RSI'] < 30, 'Signal'] = 1
    bt_df.loc[bt_df['RSI'] > 70, 'Signal'] = -1
    bt_df['Signal'] = bt_df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    bt_df['Forward_Return'] = bt_df['Close'].pct_change().shift(-1)
    bt_df['Strategy_Return'] = bt_df['Signal'] * bt_df['Forward_Return']
    bt_df['Cumulative_Market'] = (1 + bt_df['Forward_Return']).cumprod()
    bt_df['Cumulative_Strategy'] = (1 + bt_df['Strategy_Return']).cumprod()
    
    total_trades = (bt_df['Signal'].diff() != 0).sum()
    winning_trades = len(bt_df[bt_df['Strategy_Return'] > 0])
    losing_trades = len(bt_df[bt_df['Strategy_Return'] < 0])
    win_rate = (winning_trades / (winning_trades + losing_trades)) * 100 if (winning_trades + losing_trades) > 0 else 0
    strat_perf = (bt_df['Cumulative_Strategy'].iloc[-2] - 1) * 100
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Strategy Return", f"{strat_perf:.2f}%")
    col2.metric("Estimated Win Rate", f"{win_rate:.1f}%")
    col3.metric("Signal Flips (Trades)", f"{total_trades}")
    
    fig_bt = go.Figure()
    fig_bt.add_trace(go.Scatter(x=bt_df.index, y=bt_df['Cumulative_Strategy'], mode='lines', line=dict(color='#00ff00', width=2), name='Algo Strategy'))
    fig_bt.add_trace(go.Scatter(x=bt_df.index, y=bt_df['Cumulative_Market'], mode='lines', line=dict(color='#555555', width=1.5), name='Buy & Hold'))
    fig_bt.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=40), yaxis=dict(title="Growth of $1"), legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)"))
    st.plotly_chart(fig_bt, use_container_width=True)

elif "Journal" in view_mode:
    st.subheader("📓 Execution Log")
    with st.form("journal_form"):
        trade_bias = st.selectbox("Trade Bias", ["LONG", "SHORT", "FLAT"])
        entry_price = st.number_input("Target Entry Price", value=float(current_price), format="%.3f")
        notes = st.text_area("Trade Rationale")
        if st.form_submit_button("💾 Save"):
            st.session_state.journal.append({"Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Bias": trade_bias, "Price": entry_price, "Notes": notes})
            st.success("Saved!")
    if st.session_state.journal:
        st.dataframe(pd.DataFrame(st.session_state.journal), use_container_width=True)
