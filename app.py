import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import pytz
import logging
from typing import Optional, Dict, List
import json
import os

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📌 상수 정의
LOTTO_API_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber"
LOTTO_START_DATE = date(2002, 12, 7)  # 1회차 날짜
KST = pytz.timezone("Asia/Seoul")
SATURDAY_DRAW_HOUR = 21  # 토요일 추첨 시간
DEFAULT_LOAD_COUNT = 100  # 기본 로딩 회차 수
ADDITIONAL_LOAD_COUNT = 200  # 추가 로딩 회차 수
CACHE_FILE = "lotto_cache.json"  # 오프라인 캐시 파일

# 🔄 오프라인 캐시 관리
def save_to_cache(df: pd.DataFrame):
    """데이터를 로컬 캐시에 저장합니다."""
    try:
        cache_data = {
            "data": df.to_dict('records'),
            "last_updated": datetime.now(KST).isoformat(),
            "total_rounds": len(df)
        }
        
        # Streamlit의 임시 디렉토리 사용
        cache_path = os.path.join(st.session_state.get('cache_dir', '.'), CACHE_FILE)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"캐시 저장 완료: {len(df)}회차")
        return True
    except Exception as e:
        logger.error(f"캐시 저장 실패: {e}")
        return False

def load_from_cache() -> Optional[pd.DataFrame]:
    """로컬 캐시에서 데이터를 불러옵니다."""
    try:
        cache_path = os.path.join(st.session_state.get('cache_dir', '.'), CACHE_FILE)
        if not os.path.exists(cache_path):
            return None
        
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        df = pd.DataFrame(cache_data['data'])
        last_updated = datetime.fromisoformat(cache_data['last_updated'])
        
        # 캐시가 24시간 이내인 경우만 사용
        if (datetime.now(KST) - last_updated).total_seconds() < 86400:  # 24시간
            logger.info(f"캐시에서 데이터 로딩: {len(df)}회차")
            return df
        else:
            logger.info("캐시 데이터가 만료됨")
            return None
            
    except Exception as e:
        logger.error(f"캐시 로딩 실패: {e}")
        return None

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

# ⚙️ 점진적 데이터 로딩 (개선됨)
def load_lotto_data_progressive() -> pd.DataFrame:
    """
    점진적으로 로또 데이터를 불러옵니다.
    오프라인 캐시 우선, 온라인 로딩 후순위
    """
    latest_round = get_latest_round()
    
    # 세션 상태 초기화
    if 'loaded_rounds' not in st.session_state:
        st.session_state.loaded_rounds = 0
        st.session_state.lotto_data = pd.DataFrame()
        st.session_state.initial_load_message_shown = False
        st.session_state.cache_dir = os.getcwd()  # 현재 디렉토리
    
    # 첫 로딩 시도
    if st.session_state.loaded_rounds == 0:
        # 1. 먼저 캐시에서 시도
        cached_df = load_from_cache()
        if cached_df is not None and not cached_df.empty:
            # 캐시 데이터가 최신인지 확인
            cached_latest = cached_df['회차'].max()
            if cached_latest >= latest_round - 5:  # 5회차 이내면 사용
                st.session_state.lotto_data = cached_df
                st.session_state.loaded_rounds = len(cached_df)
                
                if not st.session_state.initial_load_message_shown:
                    st.success(f"💾 오프라인 캐시에서 {len(cached_df)}회차 데이터를 불러왔습니다!")
                    st.session_state.initial_load_message_shown = True
                
                return cached_df
        
        # 2. 캐시가 없거나 오래된 경우 온라인 로딩
        load_count = min(DEFAULT_LOAD_COUNT, latest_round)
        start_round = max(1, latest_round - load_count + 1)
        end_round = latest_round
        
        if not st.session_state.initial_load_message_shown:
            if cached_df is not None:
                st.info(f"🔄 캐시가 오래되어 최신 {load_count}회차 데이터를 새로 로딩합니다.")
            else:
                st.info(f"⚡ 빠른 시작을 위해 최근 {load_count}회차를 먼저 로딩합니다.")
            st.session_state.initial_load_message_shown = True
        
        df = load_lotto_data_range(start_round, end_round)
        
        if not df.empty:
            st.session_state.lotto_data = df
            st.session_state.loaded_rounds = load_count
            
            # 캐시에 저장
            save_to_cache(df)
        
        return df
    else:
        return st.session_state.lotto_data

# ⚙️ 추가 데이터 로딩 (개선됨)
def load_additional_data(count: int = ADDITIONAL_LOAD_COUNT):
    """지정된 수만큼 추가 과거 데이터를 로딩합니다."""
    current_df = st.session_state.lotto_data
    
    if current_df.empty:
        st.warning("⚠️ 기본 데이터를 먼저 로딩해주세요.")
        return
    
    current_min_round = current_df['회차'].min()
    
    # 추가로 로딩할 범위 계산
    additional_count = min(count, current_min_round - 1)
    
    if additional_count <= 0:
        st.warning("📋 모든 데이터가 이미 로딩되었습니다!")
        return
    
    start_round = max(1, current_min_round - additional_count)
    end_round = current_min_round - 1
    
    with st.spinner(f"📚 {start_round}~{end_round} 회차 ({additional_count}개) 추가 로딩 중..."):
        # 추가 데이터 로딩
        additional_df = load_lotto_data_range(start_round, end_round)
        
        if not additional_df.empty:
            # 기존 데이터와 합치기
            combined_df = pd.concat([additional_df, current_df], ignore_index=True)
            combined_df = combined_df.sort_values('회차').reset_index(drop=True)
            
            st.session_state.lotto_data = combined_df
            st.session_state.loaded_rounds = len(combined_df)
            
            # 캐시 업데이트
            save_to_cache(combined_df)
            
            st.success(f"✅ {additional_count}회차 추가 완료! 총 {len(combined_df)}회차 데이터 준비됨")
            st.rerun()
        else:
            st.error("❌ 추가 데이터 로딩에 실패했습니다.")

# ⚙️ 전체 데이터 로딩
def load_all_data():
    """전체 데이터를 로딩합니다."""
    latest_round = get_latest_round()
    
    with st.spinner(f"📊 전체 {latest_round}회차 데이터 로딩 중... (시간이 다소 걸릴 수 있습니다)"):
        full_df = load_lotto_data_range(1, latest_round)
        
        if not full_df.empty:
            st.session_state.lotto_data = full_df
            st.session_state.loaded_rounds = len(full_df)
            
            # 캐시에 저장
            save_to_cache(full_df)
            
            st.success(f"✅ 전체 {len(full_df)}회차 데이터 로딩 완료!")
            st.rerun()
        else:
            st.error("❌ 전체 데이터 로딩에 실패했습니다.")

# ⚙️ 데이터 상태 체크
def check_data_freshness() -> tuple[bool, str]:
    """데이터의 최신성을 체크합니다."""
    try:
        current_df = st.session_state.get('lotto_data', pd.DataFrame())
        if current_df.empty:
            return False, "데이터 없음"
        
        latest_round = get_latest_round()
        data_latest = current_df['회차'].max()
        
        if data_latest >= latest_round:
            return True, "최신"
        elif latest_round - data_latest <= 2:
            return True, "거의 최신"
        else:
            return False, f"{latest_round - data_latest}회차 뒤처짐"
            
    except Exception as e:
        logger.error(f"데이터 최신성 체크 실패: {e}")
        return False, "확인 불가"

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

# 📱 사이드바 UI (개선됨)
def render_sidebar():
    """개선된 사이드바를 렌더링합니다."""
    with st.sidebar:
        st.header("⚙️ 데이터 관리")
        
        # 현재 로딩 상태 표시
        if 'loaded_rounds' in st.session_state and st.session_state.loaded_rounds > 0:
            total_available = get_latest_round()
            loaded_rounds = st.session_state.loaded_rounds
            loaded_pct = (loaded_rounds / total_available) * 100
            
            # 데이터 상태 체크
            is_fresh, freshness_status = check_data_freshness()
            status_color = "🟢" if is_fresh else "🟡"
            
            st.metric(
                "로딩된 데이터", 
                f"{loaded_rounds:,}회차",
                f"{loaded_pct:.1f}% | {status_color} {freshness_status}"
            )
            
            # 데이터 범위 표시
            current_df = st.session_state.lotto_data
            if not current_df.empty:
                min_round = current_df['회차'].min()
                max_round = current_df['회차'].max()
                st.caption(f"📊 범위: {min_round}~{max_round}회차")
            
            st.divider()
            
            # 데이터 로딩 옵션들
            st.subheader("📊 데이터 확장")
            
            # 추가 200회차 로딩
            remaining_rounds = max(0, current_df['회차'].min() - 1) if not current_df.empty else 0
            can_load_more = remaining_rounds > 0
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    f"📚 +200회차", 
                    disabled=not can_load_more,
                    use_container_width=True,
                    help=f"추가로 200회차 로딩 (남은 회차: {remaining_rounds}개)"
                ):
                    load_additional_data(200)
            
            with col2:
                if st.button(
                    f"📑 +500회차", 
                    disabled=not can_load_more,
                    use_container_width=True,
                    help=f"추가로 500회차 로딩 (남은 회차: {remaining_rounds}개)"
                ):
                    load_additional_data(500)
            
            # 전체 데이터 로딩
            if loaded_pct < 100:
                if st.button("📊 전체 데이터 로딩", use_container_width=True):
                    load_all_data()
            
        else:
            # 초기 상태
            st.info("🚀 데이터를 불러오는 중입니다...")
        
        st.divider()
        
        # 분석 옵션
        st.subheader("🔧 분석 옵션")
        show_bonus = st.checkbox("보너스 번호 포함", value=False)
        
        st.divider()
        
        # 캐시 및 새로고침 옵션
        st.subheader("🔄 데이터 관리")
        
        # 캐시 상태 표시
        cache_exists = os.path.exists(os.path.join(st.session_state.get('cache_dir', '.'), CACHE_FILE))
        if cache_exists:
            st.caption("💾 오프라인 캐시 사용 가능")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 새로고침", use_container_width=True, help="온라인에서 최신 데이터 다시 로딩"):
                # 세션 상태 초기화
                for key in ['loaded_rounds', 'lotto_data', 'initial_load_message_shown']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.cache_data.clear()
                st.rerun()
        
        with col2:
            if st.button("🗑️ 캐시 삭제", use_container_width=True, help="저장된 오프라인 데이터 삭제"):
                try:
                    cache_path = os.path.join(st.session_state.get('cache_dir', '.'), CACHE_FILE)
                    if os.path.exists(cache_path):
                        os.remove(cache_path)
                        st.success("캐시 삭제 완료!")
                    else:
                        st.info("삭제할 캐시가 없습니다.")
                except Exception as e:
                    st.error(f"캐시 삭제 실패: {e}")
        
        return show_bonus

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
    
    # 사이드바 렌더링
    show_bonus = render_sidebar()
    
    # 메인 컨텐츠
    try:
        # 연결 상태 체크
        try:
            test_response = requests.get("https://www.google.com", timeout=3)
            online_status = "🟢 온라인"
        except:
            online_status = "🔴 오프라인"
        
        # 상태 표시
        status_col1, status_col2 = st.columns([3, 1])
        with status_col2:
            st.caption(f"연결상태: {online_status}")
        
        # 데이터 로딩
        df = load_lotto_data_progressive()
        
        if df.empty:
            if online_status == "🔴 오프라인":
                st.error("⚠️ 오프라인 상태이며 사용 가능한 캐시 데이터가 없습니다.")
                st.info("💡 인터넷에 연결 후 데이터를 다시 로딩해주세요.")
            else:
                st.error("⚠️ 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.")
            return
        
        # 데이터 정보 표시
        latest_round_in_data = df['회차'].max()
        latest_date = df[df['회차'] == latest_round_in_data]['날짜'].iloc[0]
        min_round = df['회차'].min()
        max_round = df['회차'].max()
        
        col1, col2 = st.columns(2)
        with col1:
            st.success(f"✅ 최신 회차: **{max_round}회** ({latest_date})")
        with col2:
            st.info(f"📊 분석 범위: **{min_round}~{max_round}회** (총 {len(df):,}회차)")
        
        # 로딩 완료도 표시
        total_available = get_latest_round()
        if len(df) < total_available:
            remaining = total_available - len(df)
            completion_pct = (len(df) / total_available) * 100
            st.progress(completion_pct / 100)
            st.caption(f"💡 전체 데이터의 {completion_pct:.1f}% 로딩됨 (남은 회차: {remaining}개)")
        else:
            st.progress(1.0)
            st.caption("🎉 모든 데이터가 로딩되었습니다!")
        
        # 통계 정보
        st.subheader("📊 기본 통계")
        display_statistics(df)
        
        st.divider()
        
        # 차트 표시
        st.subheader("🎲 번호별 출현 빈도")
        freq_chart = create_frequency_chart(df)
        st.plotly_chart(freq_chart, use_container_width=True)
        
        # 상세 데이터 테이블
        with st.expander("📋 상세 데이터 보기"):
            display_df = df.tail(20).sort_values("회차", ascending=False).copy()
            
            # 번호 컬럼을 개별 컬럼으로 분리
            for i in range(6):
                display_df[f"번호{i+1}"] = display_df["번호"].apply(lambda x: x[i] if len(x) > i else None)
            
            # 표시할 컬럼 선택 (번호 컬럼 제외)
            display_columns = ["회차", "날짜"] + [f"번호{i+1}" for i in range(6)] + ["보너스"]
            display_df_final = display_df[display_columns]
            
            st.dataframe(
                display_df_final,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "회차": st.column_config.NumberColumn("회차", width="small"),
                    "날짜": st.column_config.DateColumn("날짜", width="medium"),
                    "번호1": st.column_config.NumberColumn("1번", width="small"),
                    "번호2": st.column_config.NumberColumn("2번", width="small"),
                    "번호3": st.column_config.NumberColumn("3번", width="small"),
                    "번호4": st.column_config.NumberColumn("4번", width="small"),
                    "번호5": st.column_config.NumberColumn("5번", width="small"),
                    "번호6": st.column_config.NumberColumn("6번", width="small"),
                    "보너스": st.column_config.NumberColumn("보너스", width="small")
                }
            )
            
            # 데이터 다운로드
            csv = df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSV 다운로드",
                data=csv,
                file_name=f"lotto_data_{min_round}_{max_round}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
    
    except Exception as e:
        logger.error(f"앱 실행 중 오류: {e}")
        st.error(f"애플리케이션 실행 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
