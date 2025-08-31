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
DEFAULT_LOAD_COUNT = 100  # 기본 로딩 회차 수

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
        response.raise_for_status()
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
    
    # 안전망
    logger.warning(f"최신 회차 확인 실패, 안전망 적용: {expected_round - 2}")
    return max(1, expected_round - 2)

# ⚙️ 범위별 데이터 불러오기
@st.cache_data(show_spinner=True, ttl=3600)
def load_lotto_data_range(start_round: int, end_round: int) -> pd.DataFrame:
    """
    지정된 범위의 로또 데이터를 불러옵니다.
    
    Args:
        start_round: 시작 회차
        end_round: 끝 회차
        
    Returns:
        로또 데이터가 담긴 pandas DataFrame
    """
    records = []
    total_rounds = end_round - start_round + 1
    
    # 진행상황 표시
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        for i, round_no in enumerate(range(start_round, end_round + 1)):
            # 진행상황 업데이트
            progress = (i + 1) / total_rounds
            progress_bar.progress(progress)
            status_text.text(f"데이터 로딩 중... {round_no}/{end_round} 회차")
            
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
        logger.info(f"{start_round}~{end_round} 회차 데이터 로딩 완료 ({len(df)}개)")
        return df
        
    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        logger.error(f"데이터 로딩 중 오류 발생: {e}")
        st.error(f"데이터 로딩 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()

# ⚙️ 점진적 데이터 로딩
def load_lotto_data_progressive() -> pd.DataFrame:
    """
    점진적으로 로또 데이터를 불러옵니다.
    처음에는 최근 데이터만, 필요시 더 많은 데이터를 로드합니다.
    """
    latest_round = get_latest_round()
    
    # 세션 상태 초기화
    if 'loaded_rounds' not in st.session_state:
        st.session_state.loaded_rounds = 0
        st.session_state.lotto_data = pd.DataFrame()
    
    # 기본 로딩 범위 결정
    if st.session_state.loaded_rounds == 0:
        # 처음 로딩: 최근 100회차 또는 전체 (더 적은 것)
        load_count = min(DEFAULT_LOAD_COUNT, latest_round)
        start_round = max(1, latest_round - load_count + 1)
        end_round = latest_round
        
        st.info(f"⚡ 빠른 시작을 위해 최근 {load_count}회차만 먼저 로딩합니다.")
        df = load_lotto_data_range(start_round, end_round)
        
        st.session_state.lotto_data = df
        st.session_state.loaded_rounds = load_count
        
        return df
    else:
        return st.session_state.lotto_data

# ⚙️ 추가 데이터 로딩
def load_more_data():
    """더 많은 과거 데이터를 로딩합니다."""
    latest_round = get_latest_round()
    current_df = st.session_state.lotto_data
    
    if current_df.empty:
        return
    
    current_min_round = current_df['회차'].min()
    
    # 추가로 로딩할 범위 계산
    additional_count = min(200, current_min_round - 1)  # 최대 200회차씩 추가
    
    if additional_count <= 0:
        st.warning("📋 모든 데이터가 이미 로딩되었습니다!")
        return
    
    start_round = max(1, current_min_round - additional_count)
    end_round = current_min_round - 1
    
    st.info(f"📚 {start_round}~{end_round} 회차 ({additional_count}개) 추가 로딩 중...")
    
    # 추가 데이터 로딩
    additional_df = load_lotto_data_range(start_round, end_round)
    
    if not additional_df.empty:
        # 기존 데이터와 합치기
        combined_df = pd.concat([additional_df, current_df], ignore_index=True)
        combined_df = combined_df.sort_values('회차').reset_index(drop=True)
        
        st.session_state.lotto_data = combined_df
        st.session_state.loaded_rounds += len(additional_df)
        
        st.success(f"✅ 총 {len(combined_df)}회차 데이터 준비완료!")
        st.rerun()

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
        yaxis=dict(dtick=5),
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
        st.metric("로딩된 회차", len(df))
    
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
        
        # 데이터 로딩 상태 표시
        if 'loaded_rounds' in st.session_state and st.session_state.loaded_rounds > 0:
            st.info(f"📊 현재 {st.session_state.loaded_rounds}회차 로딩됨")
            
            # 더 많은 데이터 로딩 버튼
            if st.button("📚 더 많은 과거 데이터 로딩", use_container_width=True):
                load_more_data()
        
        st.divider()
        
        analysis_rounds = st.slider(
            "최근 회차 분석 범위", 
            min_value=10, 
            max_value=100, 
            value=50,
            help="최근 몇 회차까지 추세를 분석할지 선택하세요"
        )
        
        show_bonus = st.checkbox("보너스 번호 포함", value=False)
        
        st.divider()
        
        # 데이터 새로고침
        if st.button("🔄 데이터 새로고침", use_container_width=True):
            # 세션 상태 초기화
            if 'loaded_rounds' in st.session_state:
                del st.session_state.loaded_rounds
            if 'lotto_data' in st.session_state:
                del st.session_state.lotto_data
            st.cache_data.clear()
            st.rerun()
        
        # 전체 데이터 로딩
        if st.button("📊 전체 데이터 로딩", use_container_width=True):
            latest_round = get_latest_round()
            st.info(f"🔄 전체 {latest_round}회차 데이터를 로딩합니다. 시간이 오래 걸릴 수 있습니다.")
            
            full_df = load_lotto_data_range(1, latest_round)
            if not full_df.empty:
                st.session_state.lotto_data = full_df
                st.session_state.loaded_rounds = len(full_df)
                st.success(f"✅ 전체 {len(full_df)}회차 데이터 로딩 완료!")
                st.rerun()
    
    # 데이터 로딩
    try:
        df = load_lotto_data_progressive()
        
        if df.empty:
            st.error("⚠️ 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.")
            return
        
        # 기본 정보 표시
        latest_round_in_data = df['회차'].max()
        latest_date = df[df['회차'] == latest_round_in_data]['날짜'].iloc[0]
        
        # 데이터 범위 표시
        min_round = df['회차'].min()
        max_round = df['회차'].max()
        
        col1, col2 = st.columns(2)
        with col1:
            st.success(f"✅ 최신 회차: **{max_round}회** ({latest_date})")
        with col2:
            st.info(f"📊 분석 범위: **{min_round}~{max_round}회** (총 {len(df)}회차)")
        
        # 더 많은 데이터가 있는지 확인
        total_available = get_latest_round()
        if len(df) < total_available:
            st.warning(f"💡 더 정확한 분석을 위해 **전체 {total_available}회차** 데이터를 로딩할 수 있습니다. (사이드바 참고)")
        
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
            # 분석 범위가 로딩된 데이터를 초과하지 않도록 조정
            actual_analysis_rounds = min(analysis_rounds, len(df))
            trend_chart = create_trend_chart(df, actual_analysis_rounds)
            st.plotly_chart(trend_chart, use_container_width=True)
        
        # 상세 데이터 테이블
        with st.expander("📋 상세 데이터 보기"):
            display_df = df.tail(20).sort_values("회차", ascending=False)
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True
            )
            
            # 데이터 다운로드
            csv = df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSV 다운로드",
                data=csv,
                file_name=f"lotto_data_{min_round}_{max_round}.csv",
                mime="text/csv"
            )
    
    except Exception as e:
        logger.error(f"앱 실행 중 오류: {e}")
        st.error(f"애플리케이션 실행 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
