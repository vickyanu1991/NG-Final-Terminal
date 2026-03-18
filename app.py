import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from tvDatafeed import TvDatafeed, Interval
from streamlit_autorefresh import st_autorefresh

# ==========================================
# PAGE CONFIG & AUTOREFRESH
# ==========================================
st.set_page_config(page_title="NG Quant Terminal", layout="wide", page_icon="🔥")
st_autorefresh(interval=60000, limit=None, key="data_refresh")

# ==========================================
# DIAGNOSTIC DATA ENGINES (Extended Timeouts & Error Exposing)
# ==========================================

def fetch_live_price_and_data():
    """Attempts MCX, then NYMEX, exposing the exact error if both fail."""
    error_log = ""
    
    try:
        # PLAN A: MCX Continuous Contract
        tv = TvDatafeed() 
        mcx_data = tv.get_hist(symbol='NATGAS1!', exchange='MCX', interval=Interval.in_5_minute, n_bars=100)
        
        if mcx_data is not None and not mcx_data.empty:
            current_price = float(mcx_data['close'].iloc[-1])
            return f"₹{current_price:.2f}", "MCX Live", mcx_data
        else:
            error_log += "MCX returned empty. "
    except Exception as e:
        error_log += f"TV Error: {str(e)[:20]}... "

    try:
        # PLAN B: NYMEX Proxy Continuous Contract
        tv2 = TvDatafeed()
        nymex_data = tv2.get_hist(symbol='NG1!', exchange='NYMEX', interval=Interval.in_5_minute, n_bars=100)
        
        if nymex_data is not None and not nymex_data.empty:
            current_price = float(nymex_data['close'].iloc[-1])
            return f"${current_price:.3f}", "NYMEX Proxy (Live)", nymex_data
        else:
            error_log += "NYMEX returned empty."
    except Exception as e:
        error_log += f"NYMEX Error: {str(e)[:20]}..."
        
    return "ERROR", error_log, pd.DataFrame()

def fetch_eia_inventory():
    """Scrapes EIA with a 15-second timeout."""
    url = "https://ir.eia.gov/ngs/ngs.html"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        table = soup.find('table')
        if table:
            rows = table.find_all('tr')
            for row in rows:
                if "Net Change" in row.text or "Implied Flow" in row.text:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        val = cols[1].text.strip()
                        score = 1 if "-" in val else -1
                        return f"{val} Bcf", score
        return "EIA format changed", 0
    except Exception as e:
        return f"Err: {str(e)[:15]}...", 0

def fetch_weather_trend():
    """Tracks weather with a 15-second timeout."""
    url = "https://api.open-meteo.com/v1/forecast?latitude=41.20&longitude=-77.19&daily=temperature_2m_max&past_days=1&forecast_days=14&timezone=America%2FNew_York"
    
    try:
        res = requests.get(url, timeout=15).json()
        temps = res['daily']['temperature_2m_max']
        
        today_temp = temps[1] 
        future_temp = temps[-1] 
        temp_diff = future_temp - today_temp
        
        if temp_diff < -3.0:
            return f"Bullish", 1
        elif temp_diff > 3.0:
            return f"Bearish", -1
        else:
            return "Neutral", 0
    except Exception as e:
        return f"Err: {str(e)[:15]}...", 0

def fetch_gulf_risk():
    return "Low Risk (Stable)", 0

# ==========================================
# BUILD THE TERMINAL UI
# ==========================================

st.title("🔥 NG Quant Terminal")
st.markdown("---")

price_str, price_source, chart_data = fetch_live_price_and_data()
eia_str, eia_score = fetch_eia_inventory()
weather_str, weather_score = fetch_weather_trend()
gulf_str, gulf_score = fetch_gulf_risk()

master_score = eia_score + weather_score + gulf_score

st.subheader("🧠 Master Confluence Score")
if master_score >= 1:
    st.success(f"BULLISH (+{master_score})")
elif master_score <= -1:
    st.error(f"BEARISH ({master_score})")
else:
    st.warning("NEUTRAL (0) - Chop Zone")

st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(label=f"Current Price ({price_source})", value=price_str)
with col2:
    st.metric(label="EIA Storage", value=eia_str)
with col3:
    st.metric(label="15-Day Weather", value=weather_str)
with col4:
    st.metric(label="Gulf Storm Risk", value=gulf_str)

st.markdown("---")

st.subheader(f"Live 5-Minute Action ({price_source})")

if not chart_data.empty:
    fig = go.Figure(data=[go.Candlestick(
        x=chart_data.index,
        open=chart_data['open'],
        high=chart_data['high'],
        low=chart_data['low'],
        close=chart_data['close'],
        increasing_line_color='#00ff00', 
        decreasing_line_color='#ff0000'
    )])
    fig.update_layout(template='plotly_dark', margin=dict(l=0, r=0, t=30, b=0), height=500, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error(f"Chart data unavailable. System log: {price_source}")
