import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from tvDatafeed import TvDatafeed, Interval
from streamlit_autorefresh import st_autorefresh

# ==========================================
# PAGE CONFIG & AUTOREFRESH
# ==========================================
st.set_page_config(page_title="NG Quant Terminal", layout="wide", page_icon="🔥")

# Automatically refresh the page every 60 seconds (60000 milliseconds)
st_autorefresh(interval=60000, limit=None, key="data_refresh")

# ==========================================
# DATA ENGINES (The Core Hacks)
# ==========================================

def fetch_live_price_and_data():
    """
    Attempts to fetch 5-min MCX data first. 
    If blocked, instantly falls back to NYMEX 5-min data via yfinance.
    Returns: Current Price String, Source String, Dataframe for Chart
    """
    try:
        # PLAN A: MCX Continuous Contract (5-Minute Timeframe)
        tv = TvDatafeed() 
        mcx_data = tv.get_hist(symbol='NATGAS1!', exchange='MCX', interval=Interval.in_5_minute, n_bars=100)
        
        if mcx_data is not None and not mcx_data.empty:
            current_price = float(mcx_data['close'].iloc[-1])
            return f"₹{current_price:.2f}", "MCX Live", mcx_data
    except Exception:
        pass # Fail silently and move to Plan B

    try:
        # PLAN B: NYMEX Proxy Fallback
        nymex_ticker = yf.Ticker("NG=F")
        nymex_data = nymex_ticker.history(period="2d", interval="5m")
        if not nymex_data.empty:
            current_price = float(nymex_data['Close'].iloc[-1])
            # Rename yfinance columns to match tvDatafeed lowercase style for the chart
            nymex_data = nymex_data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
            return f"${current_price:.3f}", "NYMEX Proxy", nymex_data
    except Exception:
        return "ERROR", "Data Feed Offline", pd.DataFrame()

def fetch_eia_inventory():
    """Scrapes the live EIA storage number, bypassing bot blocks."""
    url = "https://ir.eia.gov/ngs/ngs.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        table = soup.find('table')
        if table:
            rows = table.find_all('tr')
            for row in rows:
                if "Net Change" in row.text or "Implied Flow" in row.text:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        val = cols[1].text.strip()
                        # Simple scoring: Draws (negative) are bullish (+1), Injections are bearish (-1)
                        score = 1 if "-" in val else -1
                        return f"{val} Bcf", score
        return "Awaiting Release", 0
    except Exception:
        return "Data Delayed", 0

def fetch_weather_trend():
    """Uses Open-Meteo to track 15-day temperature shifts in the US East Coast."""
    url = "https://api.open-meteo.com/v1/forecast?latitude=41.20&longitude=-77.19&daily=temperature_2m_max&past_days=1&forecast_days=14&timezone=America%2FNew_York"
    
    try:
        res = requests.get(url, timeout=5).json()
        temps = res['daily']['temperature_2m_max']
        
        today_temp = temps[1] 
        future_temp = temps[-1] 
        temp_diff = future_temp - today_temp
        
        if temp_diff < -3.0:
            return f"Bullish (Colder by {abs(temp_diff):.1f}°C)", 1
        elif temp_diff > 3.0:
            return f"Bearish (Warmer by {temp_diff:.1f}°C)", -1
        else:
            return "Neutral (Stable)", 0
    except Exception:
        return "API Offline", 0

def fetch_gulf_risk():
    """Static placeholder for Gulf Storm risk. Can be upgraded to an NHC scraper later."""
    return "Low Risk (Stable)", 0

# ==========================================
# BUILD THE TERMINAL UI
# ==========================================

st.title("🔥 NG Quant Terminal")
st.markdown("---")

# 1. Fetch all data
price_str, price_source, chart_data = fetch_live_price_and_data()
eia_str, eia_score = fetch_eia_inventory()
weather_str, weather_score = fetch_weather_trend()
gulf_str, gulf_score = fetch_gulf_risk()

# 2. Calculate Master Confluence Score
master_score = eia_score + weather_score + gulf_score

# Master Score Display
st.subheader("🧠 Master Confluence Score")
if master_score >= 1:
    st.success(f"BULLISH (+{master_score}) - Look for Long Setups")
elif master_score <= -1:
    st.error(f"BEARISH ({master_score}) - Look for Short Setups")
else:
    st.warning("NEUTRAL (0) - Chop Zone / Scalp Only")

st.markdown("---")

# 3. Data Dashboard
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(label=f"Current Price ({price_source})", value=price_str)
with col2:
    st.metric(label="EIA Storage (Latest)", value=eia_str)
with col3:
    st.metric(label="15-Day Weather (East Coast)", value=weather_str)
with col4:
    st.metric(label="Gulf Storm Risk", value=gulf_str)

st.markdown("---")

# 4. Candlestick Chart
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
    
    fig.update_layout(
        template='plotly_dark',
        margin=dict(l=0, r=0, t=30, b=0),
        height=500,
        xaxis_rangeslider_visible=False
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Chart data currently unavailable. Waiting for exchange connection...")
