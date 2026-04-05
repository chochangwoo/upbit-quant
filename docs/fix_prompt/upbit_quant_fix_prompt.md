# upbit-quant 버그 수정 프롬프트

## 배경 및 현황

이 프로젝트는 업비트 기반 암호화폐 자동매매 봇(`upbit-quant`)이다.
현재 Railway.app에서 24/7 실거래 모드로 운영 중이며 (`strategy_router` 모드, ADX 국면 판단),
텔레그램 히스토리 로그 분석을 통해 아래 버그가 확인되었다.

**수정 전 반드시 전체 코드를 먼저 읽고 파악할 것.**
버그 수정 외 기존 동작을 변경하지 않는다.

---

## 수정 대상 버그 2가지

---

### 버그 1: 성과 추적 0% 고정 버그 (최우선)

**증상:**
매일 `/report` 명령 또는 일일 리포트에서 아래와 같이 항상 0으로 표시된다.
```
누적 수익률: +0.00%
최대 낙폭(MDD): 0.00%
승률: 0.0%
샤프 지수: 0.00
```
실제로 거래가 6건 이상 발생했음에도 불구하고 성과 지표가 전혀 계산되지 않는다.

**원인 (코드 확인 완료):**
- `notify/daily_report.py`의 `calculate_performance_metrics()` 함수에서:
  - 미실현 손익(`unrealized_pnl`)만 계산하고 있음.
  - MDD, 승률, 샤프 지수 계산 로직이 **아예 없음**.
  - 매도 기록(`all_sells`)에서 횟수만 카운트하고, 수익/손실 판단 로직 없음.
- `config/settings.yaml`에 `initial_capital` 항목이 없어서 누적 수익률 계산 불가능.

**수정 방향:**
1. `config/settings.yaml`에 `initial_capital: 2000000` 항목 추가 (trading 섹션 하위).
2. `notify/daily_report.py`의 `calculate_performance_metrics()` 함수 개선:
   - **누적 수익률**: (현재 총자산 - 초기자본) / 초기자본 × 100
   - **MDD**: Supabase `trades` 테이블의 매매 이력 기반으로 일별 포트폴리오 가치 추적 후 최대 낙폭 계산.
   - **승률**: 매도 기록에서 매수 평균가 대비 매도가가 높은 비율 계산.
   - **샤프 지수**: 일별 수익률의 평균/표준편차 × √365 (연환산).
3. Supabase 조회 실패 시에는 "조회 불가"로 표시하되 0으로 고정하지 않는다.
4. `strategy_name`이 `strategy_router`, `adaptive_volume`, `ma_cross` 등 어떤 값이어도 올바르게 집계되어야 한다.

---

### 버그 2: `AdaptiveVolumeStrategy` `strategy_type` 누락 속성 오류

**증상:**
3/24 로그:
```
오류 발생
트레이딩 루프 오류:
AttributeError: 'AdaptiveVolumeStrategy' object has no attribute 'strategy_type'
```
`adaptive_volume` 모드로 시작 시 즉시 크래시 발생.

**원인 (코드 확인 완료):**
- `src/strategies/adaptive_volume_strategy.py`에 `strategy_type` 속성이 없음.
- `get_strategy_name()` 메서드는 존재하지만 (`return "adaptive_volume"`), `strategy_type` 속성과는 별도.
- `src/strategies/base.py`(BaseStrategy 추상 클래스)에도 `strategy_type` 정의 없음.
- `src/trading/portfolio_executor.py`가 내부적으로 `strategy.strategy_type`을 참조하는데 해당 속성 미존재.

**수정 방향:**
1. `src/strategies/adaptive_volume_strategy.py`의 `__init__()`에 `strategy_type` 속성 추가:
   ```python
   self.strategy_type = "adaptive_volume"
   ```
2. `portfolio_executor.py`에서 `strategy.strategy_type`에 접근하는 모든 곳에
   `getattr(strategy, 'strategy_type', strategy.get_strategy_name())` 형태로 방어 처리 추가.
3. `strategy_router`를 사용하는 현재 운영 모드에서는 이 오류가 발생하지 않지만,
   향후 `adaptive_volume` 단독 모드로 전환 시에도 안전하게 작동해야 함.

---

## 해결 완료된 이전 버그 (참고용)

> 아래 항목들은 v2 업데이트(2026-03-30)에서 이미 수정되었으므로 추가 수정 불필요.

### ~~이전 버그: 리밸런싱 포지션 사이징 (DOGE 100% 집중)~~
- **상태**: ✅ 수정 완료
- `src/trading/portfolio_executor.py`의 `run_rebalance()`에서 `RiskManager.calc_orders()`로 위임.
- 매도→2초 대기→매수 순서 정상. top_k=1일 때도 정상 작동 확인.

### ~~이전 버그: 국면 판단 로직 불일치 (/regime vs /status)~~
- **상태**: ✅ 수정 완료
- `notify/command_handler.py`의 `/regime` 핸들러가 `calc_adx()` 사용하도록 v2 최신화 완료.
- `/status`도 ADX 기반 국면 정보 표시 중.

---

## 추가 요청: 텔레그램 `/status` 출력 개선

현재 `/status` 출력에 초기 자본 대비 현재 수익률이 없다.
아래 항목을 추가해줘:

```
봇 상태 (v2)
─────────────────
모드: 실거래
전략: 거래량돌파
국면: 횡보장
ADX: 11.7 | +DI: 21.0 | -DI: 20.9
대상: 13개 코인
리밸런싱: 2026-04-03 (다음까지 2일)
─────────────────
원화 잔고: 1,304,251원
코인 평가: 536,711원
총 자산: 1,840,962원
초기 자본: 2,000,000원       ← 추가
수익률: -7.95% (-159,038원)  ← 추가
─────────────────
보유 코인
  DOGE: 536,711원
```

초기 자본은 `config/settings.yaml`의 `trading.initial_capital` 항목에서 읽어오고,
없을 경우 "미설정"으로 표시.

---

## 수정 원칙

1. **최소 침습적 수정**: 버그 수정 외 기존 로직 변경 금지.
2. **Railway 환경 고려**: 환경변수 `.env` 기반, 재시작 없이 적용 가능한 수정 우선.
3. **방어적 코딩**: 모든 외부 API 호출(Supabase, Upbit, Telegram)은 try/except로 감쌀 것.
4. **로그 보강**: 버그 수정 후 관련 동작에 loguru 로그 추가 (INFO 레벨).
5. **한국어 주석**: 모든 신규 주석은 한국어로 작성.

---

## 수정 완료 후 확인 사항

수정 완료 후 아래 항목을 체크리스트로 확인하고 결과를 보고해줘:

- [ ] `/report` 실행 시 누적 수익률이 실제 거래 기반으로 계산되는가?
- [ ] `/report` 실행 시 MDD, 승률, 샤프 지수가 정상 출력되는가?
- [ ] `adaptive_volume` 모드로 실행 시 `strategy_type` 오류가 발생하지 않는가?
- [ ] `/status` 명령에 초기 자본 대비 수익률이 표시되는가?
- [ ] 모든 수정이 `strategy_router` 현재 운영 모드에서 정상 작동하는가?
- [ ] `config/settings.yaml`에 `initial_capital` 항목이 추가되었는가?
