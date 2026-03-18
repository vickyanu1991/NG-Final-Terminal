import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh

# ==========================================
# PAGE CONFIG
# ==========================================
st.set_page_config(page_title="NG Quant Terminal", layout="wide", page_icon="🔥")
st_autorefresh(interval=60000, limit=None, key="data_refresh")

# ==========================================
# THE BYPASS ENGINES (Audited for Cloud)
# ==========================================

def fetch_live_price_safe():
    """Direct Yahoo Finance API call with full Chrome User-Agent."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/NG=F?interval=5m&range=1d"
    # A full, modern browser header to bypass 403 Forbidden blocks
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        # If Yahoo blocks us, tell the UI gracefully
        if response.status_code != 200:
            return "Syncing...", f"HTTP Block: {response.status_code}", pd.DataFrame()
            
        data = response.json()
        
        # Check if the data structure is what we expect
        if not data.get('chart', {}).get('result'):
            return "Syncing...", "Empty Market Data", pd.DataFrame()
            
        result = data['chart']['result'][0]
        price = result['meta']['regularMarketPrice']
        
        # Build the chart dataframe
        timestamps = result['timestamp']
        quotes = result['indicators']['quote'][0]
        
        df = pd.DataFrame({
            'open': quotes['open'],
            'high': quotes['high'],
            'low': quotes['low'],
            'close': quotes['close']
        }, index=pd.to_datetime(timestamps, unit='s'))
        
        return f"${price:.3f}", "NYMEX Live", df.dropna()
        
    except Exception as e:
        return "Syncing...", f"Conn Err: {str(e)[:15]}", pd.DataFrame()

def fetch_eia_inventory():
    """Scrapes EIA using safe word-matching, not hardcoded positions."""
    url = "https://ir.eia.gov/ngs/ngs.html"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        table = soup.find('table')
        if table:
            for row in table.find_all('tr'):
                if "Net Change" in row.text or "Implied Flow" in row.text:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        val = cols[1].text.strip()
                        score = 1 if "-" in val else -1
                        return f"{val} Bcf", score
        return "Format Changed", 0
    except Exception as e:
        return f"Err: {str(e)[:10]}", 0

def fetch_weather_trend():
    """Standard Open-Meteo fetch."""
    url = "https://api.open-meteo.com/v1/forecast?latitude=41.20&longitude=-77.19&daily=temperature_2m_max&forecast_days=14"
    try:
        res = requests.get(url, timeout=10).json()
        diff = res['daily']['temperature_2m_max'][-1] - res['daily']['temperature_2m_max'][1]
        if diff < -3: return "Bullish (Cold)", 1
        if diff > 3: return "Bearish (Warm)", -1
        return "Neutral", 0
    except Exception as e:
        return f"Err: {str(e)[:10]}", 0

# ==========================================
# UI BUILDER
# ==========================================

st.title("🔥 NG Quant Terminal")
st.markdown("---")

price_str, price_source, chart_df = fetch_live_price_safe()
eia_str, eia_score = fetch_eia_inventory()
weather_str, weather_score = fetch_weather_trend()

master_score = eia_score + weather_score

# Confluence Box
st.subheader("🧠 Master Confluence Score")
if master_score >= 1:
    st.success(f"BULLISH (+{master_score}) - Edge for Longs")
elif master_score <= -1:
    st.error(f"BEARISH ({master_score}) - Edge for Shorts")
else:
    st.warning("NEUTRAL (0) - No Clear Edge")

# Metrics Grid
c1, c2, c3 = st.columns(3)
c1.metric(f"Current Price ({price_source})", price_str)
c2.metric("EIA Storage", eia_str)
c3.metric("15-Day Weather", weather_str)

st.markdown("---")

# Candlestick Chart
st.subheader("Live 5-Minute Action")
if not chart_df.empty:
    fig = go.Figure(data=[go.Candlestick(
        x=chart_df.index, 
        open=chart_df['open'], 
        high=chart_df['high'], 
        low=chart_df['low'], 
        close=chart_df['close'],
        increasing_line_color='#00ff00', 
        decreasing_line_color='#ff0000'
    )])
    fig.update_layout(template='plotly_dark', height=450, margin=dict(l=0, r=0, t=30, b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(f"🔄 Terminal is establishing secure handshake... Data Log: {price_source}")
