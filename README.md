[README.md](https://github.com/user-attachments/files/25468716/README.md)
# 📈 업비트 퀀트 자동매매 시스템

Python 기반의 업비트 암호화폐 자동매매 봇입니다. 퀀트 전략을 기반으로 자동으로 매매하고, 텔레그램으로 결과를 알려줍니다.

---

## ✨ 주요 기능

### 1. 자동매매 (변동성 돌파 전략)
매일 시가 기준으로 목표가를 계산하고, 돌파 시 자동으로 매수/매도를 실행합니다.
- 매수 조건: `오늘 시가 + (전일 고가 - 전일 저가) × K값` 돌파 시
- 매도 조건: 매일 오전 8시 50분 전량 매도
- K값 기본값: 0.5 (조정 가능)

### 2. 퀀트 전략 일일 리포트 (개발 예정)
매일 정해진 시간에 텔레그램으로 전략 성과를 자동 전송합니다.
- 현재 적용 중인 전략 설명
- 누적 수익률 / MDD / 승률 / 샤프 지수
- 전일 매매 내역 요약

### 3. 백테스팅 엔진 (개발 예정)
과거 데이터로 전략을 검증합니다.
- 변동성 돌파 / 듀얼 모멘텀 / RSI+볼린저밴드 / 이동평균 크로스
- 수익률 그래프, MDD, 승률, 샤프지수, 수수료(0.05%) 반영
- 결과 Supabase 저장 및 텔레그램 자동 전송

---

## 🛠 기술 스택

| 역할 | 도구 |
|------|------|
| 언어 | Python 3.13 |
| 거래소 API | pyupbit |
| 데이터베이스 | Supabase (PostgreSQL) |
| 알림 | 텔레그램 봇 |
| 스케줄링 | schedule |
| 로깅 | loguru |
| 설정 관리 | config/settings.yaml |

---

## 📁 폴더 구조

```
upbit-quant/
├── src/
│   ├── api/              # 업비트 API 연동
│   ├── strategies/       # 실거래용 매매 전략
│   ├── database/         # Supabase DB 연동
│   ├── notifications/    # 텔레그램 알림
│   └── utils/            # 공통 유틸리티
├── notify/
│   ├── telegram_bot.py   # 실시간 매매 알림
│   └── daily_report.py   # 일일 리포트 봇
├── backtest/
│   ├── engine.py         # 백테스팅 핵심 엔진
│   ├── report.py         # 결과 시각화
│   └── strategies/       # 전략별 백테스팅 구현
│       ├── volatility_breakout.py
│       ├── dual_momentum.py
│       ├── rsi_bollinger.py
│       └── ma_cross.py
├── config/
│   └── settings.yaml     # 전체 설정값
├── logs/                 # 실행 로그
├── tests/                # 테스트 코드
├── main.py               # 프로그램 진입점
├── requirements.txt      # 필요 라이브러리
├── .env.example          # 환경변수 양식
└── CLAUDE.md             # 프로젝트 규칙 및 현황
```

---

## 🚀 시작하기

### 1. 사전 준비
- [업비트 Open API 키 발급](https://upbit.com/mypage/open_api_management) (주문하기 / 조회 권한 필요)
- [Supabase 프로젝트 생성](https://supabase.com) 및 URL/KEY 확보
- [텔레그램 봇 생성](https://t.me/BotFather) 및 토큰 발급

### 2. 설치

```bash
# 저장소 클론
git clone https://github.com/your-id/upbit-quant.git
cd upbit-quant

# 가상환경 생성 및 활성화 (Windows)
python -m venv .venv
.venv\Scripts\activate

# 라이브러리 설치
pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
# .env.example을 복사하여 .env 생성
copy .env.example .env
```

`.env` 파일을 열어 아래 값들을 입력하세요:

```
UPBIT_ACCESS_KEY=업비트_액세스_키
UPBIT_SECRET_KEY=업비트_시크릿_키
SUPABASE_URL=Supabase_URL
SUPABASE_KEY=Supabase_KEY
TELEGRAM_BOT_TOKEN=텔레그램_봇_토큰
TELEGRAM_CHAT_ID=텔레그램_채팅_ID
LIVE_TRADING=false
```

### 4. 실행

```bash
# 시뮬레이션 모드 (실제 주문 없음, 테스트용)
python main.py

# 실거래 전환 시 .env에서 아래 값 변경
LIVE_TRADING=true
```

---

## ⚠️ 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요
- 처음에는 반드시 `LIVE_TRADING=false`로 충분히 테스트한 후 실거래 전환
- 암호화폐 투자는 원금 손실 가능성이 있습니다
- 이 프로젝트는 개인 학습 목적으로 제작되었으며, 투자 손실에 대한 책임을 지지 않습니다

---

## 📊 텔레그램 알림 예시

```
[업비트 퀀트봇 - 일일 리포트]
📅 2025-01-15

📊 현재 적용 전략: 변동성 돌파 (K=0.5)
→ 전날 변동폭의 50%를 오늘 시가에 더한 값 돌파 시 매수

📈 전략 성능
- 누적 수익률: +23.4%
- 최대 낙폭(MDD): -8.2%
- 승률: 58%
- 샤프지수: 1.43

🔄 어제 매매 내역
- 09:15 BTC 매수 @ 98,200,000원
- 23:59 BTC 매도 @ 99,800,000원 (+1.6%)
```

---

## 📋 개발 진행 현황

- [x] 프로젝트 구조 생성
- [x] 업비트 / Supabase / 텔레그램 연결 테스트
- [x] 변동성 돌파 전략 구현
- [x] 시뮬레이션 모드 실행 확인
- [ ] 실거래 전환 테스트
- [ ] 일일 리포트 봇 구현
- [ ] 백테스팅 엔진 구현
- [ ] 4가지 전략 백테스팅 구현
- [ ] 클라우드 서버 배포 (24/7 운영)

---

## 📜 라이선스

개인 프로젝트입니다. 무단 상업적 이용을 금합니다.
