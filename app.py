import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import pytz

# 📌 API URL
LOTTO_API_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber"

# ⚙️ 회차 데이터 가져오기
def fetch_round_data(round_no: int) -> dict:
    url = f"{LOTTO_API_URL}&drwNo={round_no}"
    try:
        res = requests.get(url, timeout=5).json()
        return res if res.get("returnValue") == "success" else None
    except:
        return None

# ⚙️ 최신 회차 찾기 (예상 회차 계산 + API 검증)
def get_latest_round() -> int:
    base_date = date(2002, 12, 7)  # 1회차 날짜
    kst = pytz.timezone("Asia/Seoul")
    now_kst = datetime.now(kst)

    # 몇 주 지났는지 계산 → 예상 회차
    weeks_passed = (now_kst.date() - base_date).days // 7
    expected_round = 1 + weeks_passed

    # 토요일 21:00 이후면 +1 회차 가능성
    if now_kst.weekday() == 5 and now_kst.hour >= 21:
        expected_round += 1

    # API 검증
    if fetch_round_data(expected_round):
        return expected_round
    elif fetch_round_data(expected_round - 1):
        return expected_round - 1
    else:
        return expected_round - 2  # 안전망

# ⚙️ 전체 데이터 불러오기
@st.cache_data(show_spinner=True)
def load_lotto_data() -> pd.DataFrame:
    latest_round = get_latest_round()
    records = []

    for rnd in range(1, latest_round + 1):
        data = fetch_round_data(rnd)
        if data:
            numbers = [data[f"drwtNo{i}"] for i in range(1, 7)]
            records.append({
                "회차": rnd,
                "날짜": data["drwNoDate"],
                "번호": numbers,
                "보너스": data["bnusNo"]
            })

    return pd.DataFrame(records)

# 📊 Streamlit 앱
st.set_page_config(page_title="로또 번호 분석기", layout="wide")
st.title("🎯 로또 번호 분석기")

df = load_lotto_data()

st.write(f"✅ 현재 최신 회차: **{df['회차'].max()}회 ({df.iloc[-1]['날짜']})**")

# 🎲 번호별 출현 빈도
flat_numbers = [num for row in df["번호"] for num in row]
num_counts = pd.Series(flat_numbers).value_counts().sort_index()

fig = px.bar(
    num_counts,
    labels={"index": "번호", "value": "출현 횟수"},
    title="번호별 출현 빈도"
)
st.plotly_chart(fig, use_container_width=True)

# 📈 출현 추세 (최근 50회)
recent_df = df.tail(50)
trend_data = []
for _, row in recent_df.iterrows():
    for num in row["번호"]:
        trend_data.append({"회차": row["회차"], "번호": num})
trend_df = pd.DataFrame(trend_data)

fig2 = px.scatter(
    trend_df,
    x="회차", y="번호",
    title="최근 50회 번호 분포",
    opacity=0.6
)
st.plotly_chart(fig2, use_container_width=True)
