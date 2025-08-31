import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import pytz
import logging
from typing import Optional, Dict, List

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📌 상수 정의
LOTTO_API_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber"
LOTTO_START_DATE = date(2002, 12, 7)  # 1회차 날짜
KST = pytz.timezone("Asia/Seoul")
SATURDAY_DRAW_HOUR = 21  # 토요일 추첨 시간

# ⚙️ 회차 데이터 가져오기
def fetch_round_data(round_no: int) -> Optional[Dict]:
    """
    특정 회차의 로또 데이터를 API에서 가져옵니다.
    
    Args:
        round_no: 로또 회차 번호
        
    Returns:
        성공시 로또 데이터 딕셔너리, 실패시 None
    """
    url = f"{LOTTO_API_URL}&drwNo={round_no}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # HTTP 에러 확인
        data = response.json()
        
        if data.get("returnValue") == "success":
            return data
        else:
            logger.warning(f"API 응답 실패 - 회차: {round_no}, 응답: {data.get('returnValue')}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"API 요청 실패 - 회차: {round_no}, 에러: {e}")
        return None
    except ValueError as e:
        logger.error(f"JSON 파싱 실패 - 회차: {round_no}, 에러: {e}")
        return None

# ⚙️ 최신 회차 찾기
def get_latest_round() -> int:
    """
    현재 최신 회차를 찾습니다.
    
    Returns:
        최신 회차 번호
    """
    now_kst = datetime.now(KST)
    
    # 예상 회차 계산
    weeks_passed = (now_kst.date() - LOTTO_START_DATE).days // 7
    expected_round = 1 + weeks_passed
    
    # 토요일 21:00 이후면 다음 회차 가능성 체크
    if now_kst.weekday() == 5 and now_kst.hour >= SATURDAY_DRAW_HOUR:
        expected_round += 1
    
    # API 검증 (최대 3회차 뒤까지 확인)
    for offset in range(0, -4, -1):
        round_to_check = expected_round + offset
        if round_to_check >= 1 and fetch_round_data(round_to_check):
            logger.info(f"최신 회차 확인: {round_to_check}")
            return round_to_check
    
    # 안전망: 계산된 회차에서 2를 뺀 값 반환
    logger.warning(f"최신 회차 확인 실패, 안전망 적용: {expected_round - 2}")
    return max(1, expected_round - 2)

# ⚙️ 전체 데이터 불러오기
@st.cache_data(show_spinner=True, ttl=3600)  # 1시간 캐시
def load_lotto_data() -> pd.DataFrame:
    """
    전체 로또 데이터를 불러와 DataFrame으로 반환합니다.
    
    Returns:
        로또 데이터가 담긴 pandas DataFrame
    """
    latest_round = get_latest_round()
    records = []
    
    # 진행상황 표시
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        for i, round_no in enumerate(range(1, latest_round + 1)):
            # 진행상황 업데이트
            progress = (i + 1) / latest_round
            progress_bar.progress(progress)
            status_text.text(f"데이터 로딩 중... {round_no}/{latest_round} 회차")
            
            data = fetch_round_data(round_no)
            if data:
                numbers = [data[f"drwtNo{i}"] for i in range(1, 7)]
                records.append({
                    "회차": round_no,
                    "날짜": data["drwNoDate"],
                    "번호": numbers,
                    "보너스": data["bnusNo"]
                })
            else:
                logger.warning(f"회차 {round_no} 데이터 로딩 실패")
        
        # 진행상황 표시 제거
        progress_bar.empty()
        status_text.empty()
        
        df = pd.DataFrame(records)
        logger.info(f"총 {len(df)}개 회차 데이터 로딩 완료")
        return df
        
    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        logger.error(f"데이터 로딩 중 오류 발생: {e}")
        st.error(f"데이터 로딩 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()

# 📊 번호 빈도 분석 차트
def create_frequency_chart(df: pd.DataFrame) -> go.Figure:
    """번호별 출현 빈도 차트를 생성합니다."""
    flat_numbers = [num for row in df["번호"] for num in row]
    num_counts = pd.Series(flat_numbers).value_counts().sort_index()
    
    # 평균선 계산
    avg_count = num_counts.mean()
    
    fig = px.bar(
        x=num_counts.index,
        y=num_counts.values,
        labels={"x": "번호", "y": "출현 횟수"},
        title="번호별 출현 빈도",
        color=num_counts.values,
        color_continuous_scale="viridis"
    )
    
    # 평균선 추가
    fig.add_hline(
        y=avg_count, 
        line_dash="dash", 
        line_color="red",
        annotation_text=f"평균: {avg_count:.1f}회"
    )
    
    fig.update_layout(
        xaxis_title="번호",
        yaxis_title="출현 횟수",
        showlegend=False
    )
    
    return fig

# 📈 최근 추세 분석 차트
def create_trend_chart(df: pd.DataFrame, recent_rounds: int = 50) -> go.Figure:
    """최근 회차의 번호 분포 차트를 생성합니다."""
    recent_df = df.tail(recent_rounds)
    trend_data = []
    
    for _, row in recent_df.iterrows():
        for num in row["번호"]:
            trend_data.append({"회차": row["회차"], "번호": num})
    
    trend_df = pd.DataFrame(trend_data)
    
    fig = px.scatter(
        trend_df,
        x="회차", 
        y="번호",
        title=f"최근 {recent_rounds}회 번호 분포",
        opacity=0.7,
        color="번호",
        color_continuous_scale="plasma"
    )
    
    fig.update_layout(
        xaxis_title="회차",
        yaxis_title="번호",
        yaxis=dict(dtick=5),  # y축 간격 조정
        showlegend=False
    )
    
    return fig

# 📊 통계 정보 표시
def display_statistics(df: pd.DataFrame):
    """기본 통계 정보를 표시합니다."""
    if df.empty:
        st.error("데이터가 없습니다.")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("총 회차", len(df))
    
    with col2:
        flat_numbers = [num for row in df["번호"] for num in row]
        most_frequent = pd.Series(flat_numbers).value_counts().index[0]
        most_count = pd.Series(flat_numbers).value_counts().iloc[0]
        st.metric("최다 출현 번호", f"{most_frequent}번", f"{most_count}회")
    
    with col3:
        least_frequent = pd.Series(flat_numbers).value_counts().index[-1]
        least_count = pd.Series(flat_numbers).value_counts().iloc[-1]
        st.metric("최소 출현 번호", f"{least_frequent}번", f"{least_count}회")
    
    with col4:
        avg_freq = pd.Series(flat_numbers).value_counts().mean()
        st.metric("평균 출현 횟수", f"{avg_freq:.1f}회")

# 📱 메인 앱
def main():
    """메인 애플리케이션 함수"""
    st.set_page_config(
        page_title="로또 번호 분석기", 
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🎯 로또 번호 분석기")
    st.markdown("**동행복권 로또 6/45 번호 분석 도구**")
    
    # 사이드바 옵션
    with st.sidebar:
        st.header("⚙️ 분석 옵션")
        analysis_rounds = st.slider(
            "최근 회차 분석 범위", 
            min_value=10, 
            max_value=100, 
            value=50,
            help="최근 몇 회차까지 추세를 분석할지 선택하세요"
        )
        
        show_bonus = st.checkbox("보너스 번호 포함", value=False)
        
        if st.button("🔄 데이터 새로고침"):
            st.cache_data.clear()
            st.rerun()
    
    # 데이터 로딩
    try:
        df = load_lotto_data()
        
        if df.empty:
            st.error("⚠️ 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.")
            return
        
        # 기본 정보 표시
        st.success(f"✅ 최신 회차: **{df['회차'].max()}회** ({df.iloc[-1]['날짜']})")
        
        # 통계 정보
        st.subheader("📊 기본 통계")
        display_statistics(df)
        
        st.divider()
        
        # 차트 표시
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🎲 번호별 출현 빈도")
            freq_chart = create_frequency_chart(df)
            st.plotly_chart(freq_chart, use_container_width=True)
        
        with col2:
            st.subheader("📈 최근 추세 분석")
            trend_chart = create_trend_chart(df, analysis_rounds)
            st.plotly_chart(trend_chart, use_container_width=True)
        
        # 상세 데이터 테이블
        with st.expander("📋 상세 데이터 보기"):
            st.dataframe(
                df.tail(20).sort_values("회차", ascending=False),
                use_container_width=True,
                hide_index=True
            )
    
    except Exception as e:
        logger.error(f"앱 실행 중 오류: {e}")
        st.error(f"애플리케이션 실행 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
