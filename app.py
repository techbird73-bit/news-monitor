"""
고유가 피해지원금 뉴스 모니터링 대시보드
- 네이버 뉴스 검색 API 연동
- 최신순 정렬
- 부정 키워드 / 개인정보 노출 자동 탐지
"""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="고유가 피해지원금 뉴스 모니터링",
    page_icon="📰",
    layout="wide",
)

# ─────────────────────────────────────────────
# 상수 정의
# ─────────────────────────────────────────────
DEFAULT_QUERY = "고유가 피해지원금"

# 부정 키워드 (사장님이 자유롭게 추가/수정 가능)
NEGATIVE_KEYWORDS = [
    "불편", "장애", "오류", "지연", "차질", "혼란", "실패",
    "누락", "민원", "항의", "비판", "논란", "문제점", "지적",
    "개인정보", "유출", "노출", "누설", "해킹", "도용", "사기",
]

# 개인정보 정규식 패턴
PHONE_PATTERN = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")
RESIDENT_PATTERN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")
ADDRESS_PATTERN = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|"
    r"전북|전남|경북|경남|제주)[\s가-힣]*(?:시|군|구)\s*[가-힣]+(?:동|읍|면|리|로|길)\s*\d*"
)

# 도메인 → 언론사명 매핑 (자주 등장하는 매체 위주)
PRESS_MAPPING = {
    "chosun.com": "조선일보", "donga.com": "동아일보", "joongang.co.kr": "중앙일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "seoul.co.kr": "서울신문",
    "hankookilbo.com": "한국일보", "munhwa.com": "문화일보", "naeil.com": "내일신문",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이", "fnnews.com": "파이낸셜뉴스", "asiae.co.kr": "아시아경제",
    "heraldcorp.com": "헤럴드경제", "ajunews.com": "아주경제", "biz.chosun.com": "조선비즈",
    "yna.co.kr": "연합뉴스", "yonhapnews.co.kr": "연합뉴스",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1",
    "ytn.co.kr": "YTN", "sbs.co.kr": "SBS", "kbs.co.kr": "KBS",
    "imbc.com": "MBC", "mbc.co.kr": "MBC", "jtbc.co.kr": "JTBC",
    "ohmynews.com": "오마이뉴스", "pressian.com": "프레시안",
    "nocutnews.co.kr": "노컷뉴스", "kukinews.com": "쿠키뉴스",
    "etnews.com": "전자신문", "zdnet.co.kr": "ZDNet Korea",
    "naver.com": "네이버뉴스",
}

# ─────────────────────────────────────────────
# 유틸리티 함수
# ─────────────────────────────────────────────
def clean_html(text: str) -> str:
    """HTML 태그와 엔티티 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in {
        "&quot;": '"', "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&apos;": "'", "&#39;": "'", "&nbsp;": " ",
    }.items():
        text = text.replace(old, new)
    return text.strip()


def get_press_name(link: str, original_link: str) -> str:
    """링크에서 언론사명 추출"""
    for url in (original_link, link):
        if not url:
            continue
        try:
            domain = urlparse(url).netloc.lower().replace("www.", "")
            if domain in PRESS_MAPPING:
                return PRESS_MAPPING[domain]
            for key, name in PRESS_MAPPING.items():
                if key in domain:
                    return name
            parts = domain.split(".")
            if len(parts) >= 2:
                return parts[-2].upper()
        except Exception:
            continue
    return "알 수 없음"


def parse_pub_date(pub_date: str) -> datetime:
    """RFC 2822 형식의 날짜 문자열을 datetime으로 변환"""
    try:
        return parsedate_to_datetime(pub_date)
    except Exception:
        return datetime.min


def detect_negative(title: str, description: str) -> list[str]:
    """부정 키워드와 개인정보 노출 패턴 탐지"""
    text = f"{title} {description}"
    found = [kw for kw in NEGATIVE_KEYWORDS if kw in text]
    if PHONE_PATTERN.search(text):
        found.append("📱휴대폰")
    if RESIDENT_PATTERN.search(text):
        found.append("🆔주민번호")
    if ADDRESS_PATTERN.search(text):
        found.append("🏠주소")
    return found


@st.cache_data(ttl=600, show_spinner=False)
def search_naver_news(
    query: str, client_id: str, client_secret: str,
    display: int = 100, sort: str = "date",
) -> dict:
    """네이버 뉴스 검색 API 호출 (10분 캐시)"""
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": sort}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


# ─────────────────────────────────────────────
# 사이드바: 설정
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    st.subheader("🔑 네이버 API 인증")
    client_id = st.text_input(
        "Client ID",
        value=st.secrets.get("NAVER_CLIENT_ID", ""),
        type="password",
        help="https://developers.naver.com 에서 발급",
    )
    client_secret = st.text_input(
        "Client Secret",
        value=st.secrets.get("NAVER_CLIENT_SECRET", ""),
        type="password",
    )

    st.divider()
    st.subheader("🔍 검색 옵션")
    query = st.text_input("검색어", value=DEFAULT_QUERY)
    display_count = st.slider("검색 결과 수", 10, 100, 50, step=10)

    st.divider()
    st.subheader("👁️ 표시 옵션")
    show_negative_only = st.checkbox("부정 기사만 표시")

    st.divider()
    st.subheader("🔁 자동 새로고침")
    refresh_options = {
        "1분": 60_000,
        "5분": 300_000,
        "10분": 600_000,
        "30분": 1_800_000,
        "60분": 3_600_000,
        "사용 안 함": 0,
    }
    refresh_label = st.selectbox(
        "갱신 주기",
        list(refresh_options.keys()),
        index=2,  # 기본값: 10분
    )
    user_refresh_interval = refresh_options[refresh_label]

    if st.button("🗑️ 캐시 비우기", use_container_width=True,
                 help="API 응답 캐시를 모두 삭제하고 새로 호출합니다"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    with st.expander("📋 탐지 규칙 보기"):
        st.caption("**부정 키워드**")
        st.caption(", ".join(NEGATIVE_KEYWORDS))
        st.caption("**자동 탐지 패턴**")
        st.caption("• 휴대폰번호 (010-XXXX-XXXX)")
        st.caption("• 주민등록번호 (XXXXXX-XXXXXXX)")
        st.caption("• 주소 (시·도 + 시·군·구 + 동·읍·면)")

# ─────────────────────────────────────────────
# 자동 새로고침 (사이드바 설정값 적용)
# ─────────────────────────────────────────────
if user_refresh_interval > 0:
    auto_refresh_count = st_autorefresh(
        interval=user_refresh_interval,
        key="news_auto_refresh",
    )
else:
    auto_refresh_count = 0

# ─────────────────────────────────────────────
# 메인 화면
# ─────────────────────────────────────────────
header_col1, header_col2 = st.columns([5, 1])
with header_col1:
    st.title("📰 고유가 피해지원금 뉴스 모니터링")
with header_col2:
    st.write("")  # 수직 정렬용 여백
    if st.button("🔄 새로고침", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

now = datetime.now()
if user_refresh_interval > 0:
    st.caption(
        f'🔍 검색어: **"{query}"**　|　'
        f"🕒 마지막 갱신: **{now.strftime('%Y-%m-%d %H:%M:%S')}**　|　"
        f"🔁 자동 갱신: **{refresh_label}마다** "
        f"(자동 새로고침 {auto_refresh_count}회 실행됨)"
    )
else:
    st.caption(
        f'🔍 검색어: **"{query}"**　|　'
        f"🕒 마지막 갱신: **{now.strftime('%Y-%m-%d %H:%M:%S')}**　|　"
        f"🔁 자동 갱신: **사용 안 함** (수동 새로고침 버튼만 사용)"
    )

# API 키 확인
if not client_id or not client_secret:
    st.warning("⚠️ 사이드바에서 네이버 API의 Client ID와 Client Secret을 입력해 주세요.")
    with st.expander("📖 API 키 발급 방법", expanded=True):
        st.markdown("""
        1. [네이버 개발자센터](https://developers.naver.com/apps/#/register) 접속
        2. **애플리케이션 등록** 클릭
        3. **애플리케이션 이름** 입력 (예: 뉴스모니터링)
        4. **사용 API**에서 **검색** 선택
        5. **환경**: WEB 설정 (URL은 `http://localhost` 입력)
        6. 등록 후 발급된 **Client ID**, **Client Secret**을 사이드바에 입력
        
        > 무료 일일 25,000건 호출 가능합니다.
        """)
    st.stop()

# 검색 실행
try:
    with st.spinner(f'"{query}" 검색 중...'):
        data = search_naver_news(
            query, client_id, client_secret,
            display=display_count, sort="date",
        )
except requests.exceptions.HTTPError as e:
    st.error(f"❌ 네이버 API 호출 실패: {e}\n\nClient ID/Secret을 확인해 주세요.")
    st.stop()
except Exception as e:
    st.error(f"❌ 오류 발생: {e}")
    st.stop()

items = data.get("items", [])
if not items:
    st.info("🔍 검색 결과가 없습니다. 다른 검색어를 시도해 보세요.")
    st.stop()

# 데이터 가공
articles = []
for item in items:
    title = clean_html(item.get("title", ""))
    description = clean_html(item.get("description", ""))
    negatives = detect_negative(title, description)
    articles.append({
        "title": title,
        "description": description,
        "link": item.get("link", ""),
        "original_link": item.get("originallink", ""),
        "press": get_press_name(item.get("link", ""), item.get("originallink", "")),
        "pub_date": parse_pub_date(item.get("pubDate", "")),
        "negatives": negatives,
        "is_negative": bool(negatives),
    })

# 최신순 정렬
articles.sort(key=lambda x: x["pub_date"], reverse=True)

# ─────────────────────────────────────────────
# 통계 요약
# ─────────────────────────────────────────────
total = len(articles)
neg_count = sum(1 for a in articles if a["is_negative"])
pos_count = total - neg_count
press_count = len({a["press"] for a in articles})

c1, c2, c3, c4 = st.columns(4)
c1.metric("📊 전체 기사", f"{total:,}건")
c2.metric(
    "⚠️ 부정 기사", f"{neg_count:,}건",
    delta=f"{neg_count / total * 100:.1f}%" if total else "0%",
    delta_color="inverse",
)
c3.metric("✅ 일반 기사", f"{pos_count:,}건")
c4.metric("🗞️ 언론사 수", f"{press_count:,}곳")

# ─────────────────────────────────────────────
# CSV 다운로드
# ─────────────────────────────────────────────
df = pd.DataFrame([{
    "제목": a["title"],
    "언론사": a["press"],
    "발행일": a["pub_date"].strftime("%Y-%m-%d %H:%M") if a["pub_date"] != datetime.min else "",
    "내용": a["description"],
    "부정요소": ", ".join(a["negatives"]),
    "링크": a["link"],
} for a in articles])

st.download_button(
    "📥 전체 결과 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"news_{query.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)

# ─────────────────────────────────────────────
# 기사 목록
# ─────────────────────────────────────────────
display_articles = (
    [a for a in articles if a["is_negative"]] if show_negative_only else articles
)

st.divider()
st.subheader(f"📋 검색 결과 ({len(display_articles):,}건)")

if not display_articles:
    st.info("표시할 기사가 없습니다.")

for a in display_articles:
    with st.container(border=True):
        # 제목 라인
        if a["is_negative"]:
            st.markdown(
                f'<div style="margin-bottom:0.5rem;">'
                f'<a href="{a["link"]}" target="_blank" '
                f'style="color:#d32f2f; font-weight:700; font-size:18px; '
                f'text-decoration:none;">{a["title"]}</a>'
                f'<span style="background:#ffebee; color:#d32f2f; padding:3px 10px; '
                f'border-radius:12px; font-size:12px; margin-left:10px; '
                f'font-weight:600; vertical-align:middle;">⚠️ 부정적</span>'
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="margin-bottom:0.5rem;">'
                f'<a href="{a["link"]}" target="_blank" '
                f'style="color:#1f1f1f; font-weight:600; font-size:18px; '
                f'text-decoration:none;">{a["title"]}</a></div>',
                unsafe_allow_html=True,
            )

        # 메타 정보
        date_str = (
            a["pub_date"].strftime("%Y-%m-%d %H:%M")
            if a["pub_date"] != datetime.min else "날짜 미상"
        )
        st.caption(f"🗞️ **{a['press']}**　|　📅 {date_str}")

        # 본문 일부
        st.write(a["description"])

        # 탐지된 부정 요소 배지
        if a["negatives"]:
            badges = " ".join([
                f'<span style="background:#fff3e0; color:#e65100; '
                f'padding:2px 8px; border-radius:4px; font-size:12px; '
                f'margin-right:4px;">{n}</span>'
                for n in a["negatives"]
            ])
            st.markdown(
                f'<div style="margin-top:0.5rem;">'
                f'<span style="font-size:12px; color:#666;">탐지된 요소: </span>'
                f"{badges}</div>",
                unsafe_allow_html=True,
            )
