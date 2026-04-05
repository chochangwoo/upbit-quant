# 횡보장 BB+RSI 평균회귀 전략 + 자동 스위칭 구현

## 배경 및 목표

현재 `upbit-quant` 프로젝트에서 **적응형 거래량돌파 전략**으로 13개 코인을 대상으로 3일 리밸런싱 주기로 Railway.app에서 실거래 운영 중이다.

시장 국면 감지 로직이 이미 구현되어 있으며, 현재 국면 판단 기준은 다음과 같다:
- **상승장(Bull)**: 가격 > SMA50 AND 20일 모멘텀 > +10%
- **하락장(Bear)**: 가격 < SMA50 AND 20일 모멘텀 < -10%
- **횡보장(Sideways)**: 그 외

**문제**: 횡보장으로 감지해도 기존 거래량돌파 전략을 그대로 실행하고 있어서, 거짓 돌파(fake breakout)에 자주 걸리고 수익이 나지 않는다.

**목표**: 횡보장 감지 시 **BB+RSI 평균회귀 전략**으로 자동 스위칭하여 횡보장에서도 수익을 내는 시스템을 구축한다.

### 백테스트 근거 (시뮬레이션 기반)

300일, 13개 코인 대상 백테스트 결과:
- BB+RSI 평균 수익률: **+2.14%** (횡보장 구간만)
- 거래량돌파 평균 수익률: **-2.08%** (횡보장 구간만)
- 현금 보유: **0%**
- BB+RSI 우위: **8/13 코인**
- BB+RSI 평균 MDD: **-1.2%** vs 거래량돌파 MDD: **-7.0%**

→ 횡보장에서 BB+RSI가 거래량돌파 대비 수익률 +4.2%p 우위, MDD 약 80% 감소

---

## 현재 시스템 구조 (참고)

```
upbit-quant/
├── src/
│   ├── api/              # 업비트 API 연동
│   ├── strategies/       # 매매 전략
│   │   ├── base.py       # 전략 추상 클래스
│   │   └── ...           # 기존 전략들
│   ├── database/         # Supabase DB 연동
│   ├── notifications/    # 텔레그램 알림
│   └── utils/            # 유틸리티
├── config/
│   └── settings.yaml     # 전략 파라미터 통합 관리
├── main.py               # 메인 실행
├── Procfile              # Railway 실행
└── CLAUDE.md
```

**기술 스택**: Python, pyupbit, Supabase, 텔레그램 봇, loguru, Railway.app

---

## 구현 요청 사항

### Phase 1: BB+RSI 평균회귀 전략 클래스 구현

#### 파일: `src/strategies/bb_rsi_mean_reversion.py`

기존 `base.py`의 전략 추상 클래스를 상속하여 구현해줘.

**전략 파라미터** (config/settings.yaml에서 관리):
```yaml
bb_rsi_strategy:
  bb_period: 20          # 볼린저밴드 이동평균 기간
  bb_std: 2.0            # 볼린저밴드 표준편차 배수
  rsi_period: 14         # RSI 계산 기간
  rsi_oversold: 30       # RSI 과매도 임계값
  rsi_overbought: 70     # RSI 과매수 임계값
  stop_loss_pct: -3.0    # 손절 기준 (%)
  take_profit_pct: 5.0   # 익절 기준 (%)
  position_size: 0.95    # 투입 비율 (자본의 95%)
```

**매수 조건** (모두 충족 시):
1. 현재 시장 국면이 `sideways`
2. 현재가 ≤ 볼린저밴드 하단 (BB Lower Band)
3. RSI(14) < 30 (과매도)
4. 이전 캔들에서 BB 하단 아래로 진입 후 현재 캔들에서 BB 하단 위로 복귀 시 (선택적 확인 조건)

**매도 조건** (하나라도 충족 시):
1. BB 상단 터치 + RSI > 70 (과매수) → 전량 매도
2. 현재가 ≥ BB 중간선(20일 SMA) AND 수익률 > 1% → 전량 매도 (보수적 익절)
3. 수익률 ≤ -3% → 손절
4. 수익률 ≥ +5% → 익절
5. 시장 국면이 `sideways`가 아닌 것으로 전환 → 즉시 청산

**지표 계산 함수** (pyupbit 일봉 데이터 기반):
```python
def calculate_bollinger_bands(df, period=20, std_dev=2.0):
    """볼린저밴드 상단/중간/하단 계산"""
    df['bb_mid'] = df['close'].rolling(period).mean()
    df['bb_std'] = df['close'].rolling(period).std()
    df['bb_upper'] = df['bb_mid'] + std_dev * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - std_dev * df['bb_std']
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] * 100
    return df

def calculate_rsi(df, period=14):
    """RSI 계산"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df
```

---

### Phase 2: 전략 자동 스위칭 로직 (Strategy Router)

#### 파일: `src/strategies/strategy_router.py`

시장 국면에 따라 전략을 자동으로 선택하고 실행하는 라우터 클래스를 구현해줘.

```python
class StrategyRouter:
    """시장 국면에 따라 적절한 전략을 자동 선택"""
    
    def __init__(self, strategies_config):
        self.strategies = {
            'bull': VolumeBreakoutStrategy,      # 상승장 → 기존 거래량돌파
            'bear': CashHoldStrategy,             # 하락장 → 현금 보유 (또는 축소 운영)
            'sideways': BBRSIMeanReversion,       # 횡보장 → BB+RSI 평균회귀
        }
        self.current_regime = None
        self.current_strategy = None
        self.regime_history = []  # 국면 전환 이력 기록
    
    def detect_regime(self, btc_df):
        """BTC 데이터 기반 시장 국면 판단 (기존 로직 유지)"""
        price = btc_df['close'].iloc[-1]
        sma50 = btc_df['close'].rolling(50).mean().iloc[-1]
        momentum_20d = (price / btc_df['close'].iloc[-20] - 1) * 100
        
        if price > sma50 and momentum_20d > 10:
            return 'bull'
        elif price < sma50 and momentum_20d < -10:
            return 'bear'
        else:
            return 'sideways'
    
    def switch_strategy(self, new_regime):
        """
        국면 전환 시 전략 교체
        - 기존 전략의 보유 포지션 정리
        - 새 전략으로 전환
        - 텔레그램 알림 전송
        - 전환 이력 DB 기록
        """
        pass
    
    def execute(self, market_data):
        """현재 전략 실행"""
        regime = self.detect_regime(market_data['KRW-BTC'])
        if regime != self.current_regime:
            self.switch_strategy(regime)
        return self.current_strategy.execute(market_data)
```

**국면 전환 시 동작**:
1. 기존 전략의 보유 포지션을 모두 시장가 매도
2. 새로운 전략 객체로 교체
3. 텔레그램으로 국면 전환 알림 전송:
   ```
   🔄 시장 국면 전환 감지
   ──────────────
   이전: 상승장 (거래량돌파)
   현재: 횡보장 (BB+RSI 평균회귀)
   ──────────────
   BTC: 100,391,000원
   SMA50: 101,761,100원
   20일 모멘텀: +2.6%
   ──────────────
   보유 포지션 전량 청산 완료
   새 전략 적용 시작
   ```
4. Supabase `strategy_switches` 테이블에 전환 이력 기록

**국면 전환 안정성 처리**:
- 국면 전환 후 최소 2일은 동일 국면 유지 시에만 전략 교체 (잦은 전환 방지)
- `regime_confirmation_days: 2` 파라미터로 설정

---

### Phase 3: 하락장 전략 (Cash Hold / Defensive)

#### 파일: `src/strategies/cash_hold.py`

하락장에서는 현금 보유를 기본으로 하되, 선택적으로 방어적 전략을 실행할 수 있도록 구현해줘.

```python
class CashHoldStrategy:
    """하락장 방어 전략 — 현금 비중 최대화"""
    
    def execute(self, market_data):
        # 기존 포지션이 있다면 전량 매도
        # 신규 매수 금지
        # 텔레그램으로 하락장 방어 모드 알림
        pass
```

---

### Phase 4: config/settings.yaml 업데이트

기존 settings.yaml에 아래 섹션 추가:

```yaml
# ─── 시장 국면 감지 설정 ───
regime_detection:
  sma_period: 50              # 국면 판단용 SMA 기간
  momentum_period: 20         # 모멘텀 계산 기간
  bull_threshold: 10          # 상승장 모멘텀 임계값 (%)
  bear_threshold: -10         # 하락장 모멘텀 임계값 (%)
  confirmation_days: 2        # 국면 전환 확인 대기일

# ─── 전략별 설정 ───
strategies:
  # 상승장/기본 전략: 적응형 거래량돌파 (기존)
  volume_breakout:
    enabled: true
    regime: bull
    # ... 기존 파라미터 유지 ...
  
  # 횡보장 전략: BB+RSI 평균회귀
  bb_rsi_mean_reversion:
    enabled: true
    regime: sideways
    bb_period: 20
    bb_std: 2.0
    rsi_period: 14
    rsi_oversold: 30
    rsi_overbought: 70
    stop_loss_pct: -3.0
    take_profit_pct: 5.0
    position_size: 0.95
    # 신호 완화 옵션 (거래 빈도가 너무 낮을 경우 조정)
    relaxed_mode: false       # true로 변경 시 아래 값 적용
    relaxed_rsi_oversold: 35  # RSI 완화
    relaxed_bb_std: 1.5       # BB 표준편차 완화
  
  # 하락장 전략: 현금 보유
  cash_hold:
    enabled: true
    regime: bear
```

---

### Phase 5: main.py 수정

기존 main.py에서 전략 실행 부분을 StrategyRouter를 통해 실행하도록 수정:

```python
# 기존 코드 (단일 전략)
# strategy = VolumeBreakoutStrategy(config)
# strategy.execute(data)

# 변경 코드 (전략 라우터)
from src.strategies.strategy_router import StrategyRouter

router = StrategyRouter(config)
router.execute(market_data)
```

**주의**: 기존 거래량돌파 전략 코드는 건드리지 말 것. StrategyRouter가 감싸는 형태로 구현.

---

### Phase 6: 텔레그램 알림 추가

기존 텔레그램 봇에 아래 알림 유형 추가:

1. **국면 전환 알림**: 국면이 바뀔 때 전략 전환 내역 전송
2. **BB+RSI 매매 알림**: 매수/매도 시 BB/RSI 지표값 포함
   ```
   📈 BB+RSI 매수 신호
   ──────────────
   코인: KRW-SOL
   매수가: 230,000원
   BB 하단: 228,500원
   RSI: 27.3
   국면: 횡보장
   ```
3. **일일 국면 리포트**: 매일 정시에 현재 국면 + 적용 전략 요약

---

### Phase 7: DB 스키마 추가

Supabase에 아래 테이블 추가:

```sql
-- 전략 전환 이력
CREATE TABLE strategy_switches (
    id              BIGSERIAL PRIMARY KEY,
    prev_regime     TEXT NOT NULL,    -- 'bull', 'bear', 'sideways'
    new_regime      TEXT NOT NULL,
    prev_strategy   TEXT NOT NULL,
    new_strategy    TEXT NOT NULL,
    btc_price       NUMERIC,
    sma50           NUMERIC,
    momentum_20d    NUMERIC,
    positions_closed JSONB,          -- 청산된 포지션 정보
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- BB+RSI 전략 거래 내역
CREATE TABLE bb_rsi_trades (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL,    -- 'buy' or 'sell'
    price           NUMERIC NOT NULL,
    amount          NUMERIC NOT NULL,
    bb_upper        NUMERIC,
    bb_mid          NUMERIC,
    bb_lower        NUMERIC,
    rsi             NUMERIC,
    bb_width        NUMERIC,
    sell_reason     TEXT,            -- 'bb_upper_rsi', 'bb_mid', 'stop_loss', 'take_profit', 'regime_change'
    pnl_pct         NUMERIC,
    regime          TEXT DEFAULT 'sideways',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 구현 시 반드시 지켜야 할 규칙

1. **기존 코드 보존**: 거래량돌파 전략 코드를 직접 수정하지 말 것. StrategyRouter로 감싸기만 할 것.
2. **Look-ahead bias 방지**: 미래 데이터를 참조하지 않도록 모든 지표는 현재까지의 데이터만 사용.
3. **API 레이트 리밋**: pyupbit API 호출 사이에 최소 0.1초 sleep. 13개 코인 순차 처리.
4. **수수료 반영**: 매수/매도 시 Upbit 수수료 0.05% 반드시 반영.
5. **에러 핸들링**: 모든 API 호출에 try-except. 실패 시 텔레그램 알림 + 로그 기록.
6. **로깅**: loguru로 모든 전략 결정 과정 로깅. 국면 판단, 지표값, 매매 신호 등.
7. **LIVE_TRADING 플래그**: `LIVE_TRADING=false`일 때는 실제 주문 없이 시뮬레이션 로그만 출력.
8. **모든 주석은 한국어**로 작성.
9. **테스트**: 각 전략 클래스는 단독 실행 가능하도록 `if __name__ == "__main__"` 포함.

---

## 구현 순서 (반드시 이 순서로)

1. `config/settings.yaml` — 새 파라미터 섹션 추가
2. `src/strategies/bb_rsi_mean_reversion.py` — BB+RSI 전략 클래스
3. `src/strategies/cash_hold.py` — 하락장 방어 전략
4. `src/strategies/strategy_router.py` — 전략 라우터
5. `main.py` — StrategyRouter 연결
6. 텔레그램 알림 추가
7. Supabase 테이블 추가
8. 단독 실행 테스트 (`python -m src.strategies.bb_rsi_mean_reversion`)

---

## 검증 체크리스트

구현 완료 후 아래를 확인해줘:

- [ ] `LIVE_TRADING=false`에서 BB+RSI 전략이 시뮬레이션으로 작동하는가?
- [ ] 국면 전환 시 기존 포지션이 정상적으로 청산되는가?
- [ ] 횡보장 → 상승장 전환 시 거래량돌파 전략으로 정상 복귀하는가?
- [ ] 텔레그램으로 국면 전환 알림이 오는가?
- [ ] BB+RSI 매수 조건 (BB하단 + RSI < 30) 이 정확히 판단되는가?
- [ ] 손절(-3%) / 익절(+5%) 이 정상 작동하는가?
- [ ] Supabase에 전략 전환 이력과 거래 내역이 기록되는가?
- [ ] loguru 로그에 국면 판단 근거(BTC가격, SMA50, 모멘텀)가 기록되는가?
- [ ] 기존 거래량돌파 전략이 상승장에서 정상 작동하는가? (회귀 테스트)

---

## 향후 확장 고려사항 (지금 구현하지 않아도 됨)

- RSI 임계값을 30 → 35로, BB 표준편차를 2.0 → 1.5로 완화하는 `relaxed_mode` 토글
- 그리드 트레이딩 전략을 횡보장 대안으로 추가
- HMM(Hidden Markov Model) 기반 국면 감지로 업그레이드
- BB Width 기반 횡보장 세분화 (좁은 횡보 vs 넓은 횡보)
