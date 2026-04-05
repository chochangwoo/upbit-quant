import { useState } from "react";

const data = {
  comparison: [
    { ticker: "KRW-BTC", sideways_pct: 73, bb_return: 1.54, bb_trades: 1, bb_winrate: 100.0, bb_mdd: -1.4, bb_avg_win: 1.54, bb_avg_loss: 0, vol_return: 1.86, vol_trades: 3, vol_winrate: 66.7, vol_mdd: -8.8 },
    { ticker: "KRW-ETH", sideways_pct: 65, bb_return: -3.69, bb_trades: 1, bb_winrate: 0.0, bb_mdd: -4.3, bb_avg_win: 0, bb_avg_loss: -3.69, vol_return: 4.78, vol_trades: 2, vol_winrate: 50.0, vol_mdd: -2.5 },
    { ticker: "KRW-SOL", sideways_pct: 44, bb_return: -4.13, bb_trades: 1, bb_winrate: 0.0, bb_mdd: -5.7, bb_avg_win: 0, bb_avg_loss: -4.13, vol_return: -11.25, vol_trades: 2, vol_winrate: 0.0, vol_mdd: -11.2 },
    { ticker: "KRW-XRP", sideways_pct: 51, bb_return: 0.00, bb_trades: 0, bb_winrate: 0, bb_mdd: 0.0, bb_avg_win: 0, bb_avg_loss: 0, vol_return: 7.34, vol_trades: 1, vol_winrate: 100.0, vol_mdd: -0.1 },
    { ticker: "KRW-ADA", sideways_pct: 36, bb_return: 0.00, bb_trades: 0, bb_winrate: 0, bb_mdd: 0.0, bb_avg_win: 0, bb_avg_loss: 0, vol_return: -7.55, vol_trades: 2, vol_winrate: 0.0, vol_mdd: -7.5 },
    { ticker: "KRW-AVAX", sideways_pct: 50, bb_return: 5.09, bb_trades: 2, bb_winrate: 100.0, bb_mdd: -0.1, bb_avg_win: 2.55, bb_avg_loss: 0, vol_return: 4.85, vol_trades: 2, vol_winrate: 50.0, vol_mdd: -2.7 },
    { ticker: "KRW-LINK", sideways_pct: 35, bb_return: -3.48, bb_trades: 1, bb_winrate: 0.0, bb_mdd: -3.5, bb_avg_win: 0, bb_avg_loss: -3.48, vol_return: 0.89, vol_trades: 2, vol_winrate: 50.0, vol_mdd: -4.7 },
    { ticker: "KRW-XLM", sideways_pct: 69, bb_return: 0.00, bb_trades: 0, bb_winrate: 0, bb_mdd: 0.0, bb_avg_win: 0, bb_avg_loss: 0, vol_return: -5.25, vol_trades: 4, vol_winrate: 50.0, vol_mdd: -9.2 },
    { ticker: "KRW-DOGE", sideways_pct: 65, bb_return: 1.25, bb_trades: 1, bb_winrate: 100.0, bb_mdd: -0.1, bb_avg_win: 1.25, bb_avg_loss: 0, vol_return: -15.39, vol_trades: 4, vol_winrate: 0.0, vol_mdd: -17.4 },
    { ticker: "KRW-DOT", sideways_pct: 49, bb_return: 22.43, bb_trades: 2, bb_winrate: 100.0, bb_mdd: -0.1, bb_avg_win: 11.22, bb_avg_loss: 0, vol_return: 2.75, vol_trades: 3, vol_winrate: 66.7, vol_mdd: -6.2 },
    { ticker: "KRW-NEAR", sideways_pct: 46, bb_return: 0.00, bb_trades: 0, bb_winrate: 0, bb_mdd: 0.0, bb_avg_win: 0, bb_avg_loss: 0, vol_return: 1.56, vol_trades: 3, vol_winrate: 33.3, vol_mdd: -7.4 },
    { ticker: "KRW-ATOM", sideways_pct: 60, bb_return: 8.32, bb_trades: 1, bb_winrate: 100.0, bb_mdd: -0.6, bb_avg_win: 8.32, bb_avg_loss: 0, vol_return: -0.59, vol_trades: 4, vol_winrate: 25.0, vol_mdd: -5.9 },
    { ticker: "KRW-MATIC", sideways_pct: 39, bb_return: 0.55, bb_trades: 1, bb_winrate: 100.0, bb_mdd: -0.1, bb_avg_win: 0.55, bb_avg_loss: 0, vol_return: -11.04, vol_trades: 4, vol_winrate: 25.0, vol_mdd: -13.2 },
  ],
  summary: { bb_avg_return: 2.14, vol_avg_return: -2.08, bb_avg_winrate: 46.2, vol_avg_winrate: 39.7, bb_wins: 8, total: 13 }
};

const BarChart = ({ items, valueKey, label, color, negColor }) => {
  const max = Math.max(...items.map(i => Math.abs(i[valueKey])), 1);
  return (
    <div style={{ marginTop: 8 }}>
      {items.map((item, idx) => {
        const val = item[valueKey];
        const w = Math.abs(val) / max * 100;
        const isNeg = val < 0;
        return (
          <div key={idx} style={{ display: "flex", alignItems: "center", marginBottom: 3, fontSize: 12 }}>
            <span style={{ width: 80, fontFamily: "'JetBrains Mono', monospace", color: "#94a3b8", flexShrink: 0 }}>
              {item.ticker.replace("KRW-", "")}
            </span>
            <div style={{ flex: 1, position: "relative", height: 20, display: "flex", alignItems: "center" }}>
              <div style={{
                position: "absolute", left: isNeg ? `${50 - w/2}%` : "50%",
                width: `${w/2}%`, height: 16, borderRadius: 3,
                background: isNeg ? (negColor || "#ef4444") : (color || "#10b981"),
                opacity: 0.85, transition: "all 0.3s"
              }} />
              <div style={{ position: "absolute", left: "50%", width: 1, height: "100%", background: "#334155" }} />
            </div>
            <span style={{
              width: 65, textAlign: "right", fontFamily: "'JetBrains Mono', monospace",
              color: isNeg ? "#ef4444" : "#10b981", fontWeight: 600, fontSize: 11
            }}>
              {val > 0 ? "+" : ""}{val.toFixed(2)}%
            </span>
          </div>
        );
      })}
    </div>
  );
};

export default function Dashboard() {
  const [view, setView] = useState("overview");
  const [selectedCoin, setSelectedCoin] = useState(null);
  const { comparison, summary } = data;

  const sorted = [...comparison].sort((a, b) => b.bb_return - a.bb_return);
  const bbWinCoins = comparison.filter(c => c.bb_return > c.vol_return);
  const bbAvgMDD = comparison.reduce((s, c) => s + c.bb_mdd, 0) / comparison.length;
  const volAvgMDD = comparison.reduce((s, c) => s + c.vol_mdd, 0) / comparison.length;

  return (
    <div style={{
      minHeight: "100vh", background: "#0f172a", color: "#e2e8f0",
      fontFamily: "'Inter', -apple-system, sans-serif", padding: "24px 16px"
    }}>
      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%", background: "#f59e0b",
              boxShadow: "0 0 8px #f59e0b"
            }} />
            <span style={{ fontSize: 11, color: "#f59e0b", fontWeight: 600, letterSpacing: 2, textTransform: "uppercase" }}>
              횡보장 백테스트
            </span>
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: "4px 0", color: "#f8fafc" }}>
            BB+RSI 평균회귀 vs 거래량돌파
          </h1>
          <p style={{ fontSize: 12, color: "#64748b", margin: 0 }}>
            시뮬레이션 데이터 · 300일 · 13코인 · 횡보구간만 · 수수료 0.05%
          </p>
        </div>

        {/* Summary Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 20 }}>
          {[
            { label: "BB+RSI 평균", value: `+${summary.bb_avg_return}%`, sub: `승률 ${summary.bb_avg_winrate}%`, color: "#10b981", bg: "rgba(16,185,129,0.08)" },
            { label: "거래량돌파 평균", value: `${summary.vol_avg_return}%`, sub: `승률 ${summary.vol_avg_winrate}%`, color: "#ef4444", bg: "rgba(239,68,68,0.08)" },
            { label: "BB+RSI 우위", value: `${summary.bb_wins}/${summary.total}`, sub: `${(summary.bb_wins/summary.total*100).toFixed(0)}% 코인`, color: "#f59e0b", bg: "rgba(245,158,11,0.08)" },
          ].map((card, i) => (
            <div key={i} style={{
              background: card.bg, border: `1px solid ${card.color}22`,
              borderRadius: 10, padding: "14px 12px", textAlign: "center"
            }}>
              <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 6 }}>{card.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: card.color, fontFamily: "'JetBrains Mono', monospace" }}>
                {card.value}
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>{card.sub}</div>
            </div>
          ))}
        </div>

        {/* MDD Comparison */}
        <div style={{
          background: "rgba(239,68,68,0.05)", border: "1px solid rgba(239,68,68,0.15)",
          borderRadius: 10, padding: "12px 16px", marginBottom: 20, display: "flex", justifyContent: "space-around"
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>BB+RSI 평균 MDD</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#f59e0b", fontFamily: "'JetBrains Mono', monospace" }}>
              {bbAvgMDD.toFixed(1)}%
            </div>
          </div>
          <div style={{ width: 1, background: "#334155" }} />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>거래량돌파 평균 MDD</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#ef4444", fontFamily: "'JetBrains Mono', monospace" }}>
              {volAvgMDD.toFixed(1)}%
            </div>
          </div>
          <div style={{ width: 1, background: "#334155" }} />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>리스크 감소</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#10b981", fontFamily: "'JetBrains Mono', monospace" }}>
              {((1 - Math.abs(bbAvgMDD) / Math.abs(volAvgMDD)) * 100).toFixed(0)}%↓
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
          {["overview", "detail"].map(tab => (
            <button key={tab} onClick={() => setView(tab)} style={{
              padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
              fontSize: 12, fontWeight: 600,
              background: view === tab ? "#f59e0b" : "#1e293b",
              color: view === tab ? "#0f172a" : "#94a3b8"
            }}>
              {tab === "overview" ? "수익률 비교" : "코인별 상세"}
            </button>
          ))}
        </div>

        {view === "overview" && (
          <div>
            {/* BB+RSI Returns Chart */}
            <div style={{
              background: "#1e293b", borderRadius: 10, padding: 16, marginBottom: 12,
              border: "1px solid #334155"
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#f8fafc", marginBottom: 4 }}>
                BB+RSI 수익률 (횡보장)
              </div>
              <BarChart items={sorted} valueKey="bb_return" color="#10b981" negColor="#ef4444" />
            </div>

            {/* Volume Breakout Returns */}
            <div style={{
              background: "#1e293b", borderRadius: 10, padding: 16, marginBottom: 12,
              border: "1px solid #334155"
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#f8fafc", marginBottom: 4 }}>
                거래량돌파 수익률 (횡보장)
              </div>
              <BarChart items={sorted} valueKey="vol_return" color="#3b82f6" negColor="#ef4444" />
            </div>

            {/* Key Insight */}
            <div style={{
              background: "rgba(16,185,129,0.06)", border: "1px solid rgba(16,185,129,0.2)",
              borderRadius: 10, padding: 16
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#10b981", marginBottom: 8 }}>
                📊 핵심 인사이트
              </div>
              <div style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.7 }}>
                • BB+RSI는 <span style={{ color: "#10b981", fontWeight: 600 }}>거래 신호가 엄격</span>해 거래 횟수가 적지만, 신호 발생 시 높은 승률<br/>
                • 거래량돌파는 횡보장에서 <span style={{ color: "#ef4444", fontWeight: 600 }}>거짓 돌파</span>에 자주 걸려 평균 수익률 마이너스<br/>
                • BB+RSI의 MDD가 거래량돌파 대비 <span style={{ color: "#f59e0b", fontWeight: 600 }}>~{((1 - Math.abs(bbAvgMDD) / Math.abs(volAvgMDD)) * 100).toFixed(0)}% 낮음</span> → 자본 보존에 유리<br/>
                • 거래 없는 코인(XRP, ADA 등)은 BB+RSI 조건을 충족 못함 → <span style={{ color: "#94a3b8" }}>현금보유와 동일</span>
              </div>
            </div>
          </div>
        )}

        {view === "detail" && (
          <div>
            {comparison.map((c, idx) => {
              const isOpen = selectedCoin === idx;
              const bbBetter = c.bb_return > c.vol_return;
              const coin = c.ticker.replace("KRW-", "");
              return (
                <div key={idx} onClick={() => setSelectedCoin(isOpen ? null : idx)} style={{
                  background: "#1e293b", borderRadius: 10, marginBottom: 8, cursor: "pointer",
                  border: `1px solid ${isOpen ? "#f59e0b44" : "#334155"}`, overflow: "hidden",
                  transition: "border-color 0.2s"
                }}>
                  {/* Summary Row */}
                  <div style={{
                    display: "flex", alignItems: "center", padding: "12px 16px", gap: 12
                  }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: 8,
                      background: bbBetter ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 12, fontWeight: 700,
                      color: bbBetter ? "#10b981" : "#ef4444"
                    }}>
                      {coin}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>{c.ticker}</span>
                        <span style={{ fontSize: 11, color: "#64748b" }}>횡보 {c.sideways_pct}%</span>
                      </div>
                      <div style={{ display: "flex", gap: 16, marginTop: 4 }}>
                        <span style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace", color: c.bb_return >= 0 ? "#10b981" : "#ef4444" }}>
                          BB: {c.bb_return >= 0 ? "+" : ""}{c.bb_return.toFixed(2)}%
                        </span>
                        <span style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace", color: c.vol_return >= 0 ? "#3b82f6" : "#ef4444" }}>
                          Vol: {c.vol_return >= 0 ? "+" : ""}{c.vol_return.toFixed(2)}%
                        </span>
                        {bbBetter && <span style={{ fontSize: 10, color: "#10b981", fontWeight: 600 }}>BB 우위</span>}
                      </div>
                    </div>
                    <span style={{ color: "#64748b", fontSize: 14 }}>{isOpen ? "▲" : "▼"}</span>
                  </div>

                  {isOpen && (
                    <div style={{ padding: "0 16px 14px", borderTop: "1px solid #334155" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 12 }}>
                        {/* BB+RSI Detail */}
                        <div style={{ background: "#0f172a", borderRadius: 8, padding: 12 }}>
                          <div style={{ fontSize: 11, color: "#10b981", fontWeight: 600, marginBottom: 8 }}>BB+RSI 평균회귀</div>
                          {[
                            ["수익률", `${c.bb_return >= 0 ? "+" : ""}${c.bb_return.toFixed(2)}%`],
                            ["거래 수", `${c.bb_trades}회`],
                            ["승률", `${c.bb_winrate}%`],
                            ["MDD", `${c.bb_mdd.toFixed(1)}%`],
                          ].map(([k, v], i) => (
                            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                              <span style={{ color: "#94a3b8" }}>{k}</span>
                              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#e2e8f0" }}>{v}</span>
                            </div>
                          ))}
                        </div>
                        {/* Vol Breakout Detail */}
                        <div style={{ background: "#0f172a", borderRadius: 8, padding: 12 }}>
                          <div style={{ fontSize: 11, color: "#3b82f6", fontWeight: 600, marginBottom: 8 }}>거래량돌파</div>
                          {[
                            ["수익률", `${c.vol_return >= 0 ? "+" : ""}${c.vol_return.toFixed(2)}%`],
                            ["거래 수", `${c.vol_trades}회`],
                            ["승률", `${c.vol_winrate}%`],
                            ["MDD", `${c.vol_mdd.toFixed(1)}%`],
                          ].map(([k, v], i) => (
                            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                              <span style={{ color: "#94a3b8" }}>{k}</span>
                              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#e2e8f0" }}>{v}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Footer */}
        <div style={{
          marginTop: 20, padding: "12px 16px", background: "rgba(245,158,11,0.06)",
          border: "1px solid rgba(245,158,11,0.15)", borderRadius: 10
        }}>
          <div style={{ fontSize: 11, color: "#f59e0b", fontWeight: 600, marginBottom: 6 }}>⚠️ 시뮬레이션 데이터 유의사항</div>
          <div style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.6 }}>
            Upbit API 접근 불가로 실제 시장 통계(변동성, 횡보비율) 기반 시뮬레이션 데이터를 사용했습니다.
            실거래 적용 전 로컬 환경에서 Upbit 실제 데이터로 재검증이 필요합니다.
          </div>
        </div>
      </div>
    </div>
  );
}
