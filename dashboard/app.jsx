import { useState, useMemo, useEffect, useCallback } from "react";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ScatterChart, Scatter, ReferenceLine, Legend, Area, AreaChart } from "recharts";
import { Activity, TrendingUp, TrendingDown, AlertTriangle, CheckCircle, DollarSign, Target, BarChart3, Radio, Eye, Zap, Shield, Clock } from "lucide-react";

const API_BASE = "http://localhost:8000";

// ─── SIMULATED DATA (matches infra/db.py schema) ────────────────────────────

const generateTrades = () => {
  const categories = ["politics", "science", "sports_outcome", "geopolitics"];
  const questions = [
    "Will France hold snap elections before July 2026?",
    "Will NASA confirm microbial life on Mars by 2027?",
    "Will PSG win the Champions League 2025-26?",
    "Will the US rejoin the Paris Agreement in 2026?",
    "Will Bitcoin ETF surpass $100B AUM by June 2026?",
    "Will India land a crewed mission on the Moon by 2028?",
    "Will the WHO declare a new pandemic before 2027?",
    "Will Real Madrid win La Liga 2025-26?",
    "Will UK rejoin the EU single market by 2028?",
    "Will SpaceX Starship complete orbital refueling in 2026?",
    "Will Japan host the 2030 FIFA World Cup?",
    "Will a category 6 hurricane hit the US in 2026?",
    "Will the ICC issue new arrest warrants in 2026?",
    "Will mRNA cancer vaccines enter Phase 3 by 2027?",
    "Will France win the 2026 FIFA World Cup?",
    "Will Turkey join the EU by 2030?",
    "Will the next US Speaker be a Republican?",
    "Will CERN discover a new particle by 2027?",
    "Will the 2026 midterms flip the Senate?",
    "Will a ceasefire hold in Sudan for 90+ days?",
    "Will Argentina default on debt in 2026?",
    "Will GPT-5 be released before July 2026?",
    "Will the James Webb detect biosignatures by 2027?",
    "Will Djokovic win another Grand Slam in 2026?",
    "Will EU impose carbon border tax on US goods?",
    "Will global temps exceed 1.5C threshold in 2026?",
    "Will South Korea impeach president again in 2026?",
    "Will Liverpool win the Premier League 2025-26?",
    "Will Iran reach nuclear weapon capability by 2027?",
    "Will the UN Security Council add new permanent members?",
  ];
  const statuses = ["won", "lost", "open", "won", "won", "lost", "won", "open", "won", "lost"];
  const trades = [];
  const now = Date.now();

  for (let i = 0; i < 30; i++) {
    const daysAgo = 30 - i + Math.random() * 2;
    const ts = new Date(now - daysAgo * 86400000);
    const agentProb = 0.25 + Math.random() * 0.5;
    const marketProb = agentProb + (Math.random() - 0.6) * 0.15;
    const edgeNet = Math.abs(agentProb - marketProb) - 0.02;
    const status = statuses[i % statuses.length];
    const side = agentProb > marketProb ? "YES" : "NO";
    const entryPrice = side === "YES" ? marketProb : 1 - marketProb;
    const sizeUsdc = 5 + Math.random() * 15;
    let pnl = null;
    if (status === "won") pnl = sizeUsdc * (1 / entryPrice - 1) * 0.98;
    else if (status === "lost") pnl = -sizeUsdc;

    trades.push({
      id: i + 1,
      timestamp: ts.toISOString(),
      date: ts.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" }),
      market_id: `0x${Math.random().toString(16).slice(2, 10)}`,
      question: questions[i % questions.length],
      category: categories[i % categories.length],
      side,
      size_usdc: Math.round(sizeUsdc * 100) / 100,
      entry_price: Math.round(entryPrice * 1000) / 1000,
      agent_probability: Math.round(agentProb * 1000) / 1000,
      market_probability: Math.round(marketProb * 1000) / 1000,
      edge_net: Math.round(edgeNet * 1000) / 1000,
      confidence: Math.floor(6 + Math.random() * 4),
      status,
      pnl: pnl !== null ? Math.round(pnl * 100) / 100 : null,
    });
  }
  return trades;
};

const generateScans = () => {
  const scans = [];
  const now = Date.now();
  for (let i = 0; i < 60; i++) {
    const hoursAgo = 60 - i;
    scans.push({
      timestamp: new Date(now - hoursAgo * 3600000).toISOString(),
      hour: new Date(now - hoursAgo * 3600000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
      markets_scanned: 15 + Math.floor(Math.random() * 25),
      opportunities_found: Math.floor(Math.random() * 5),
      trades_placed: Math.floor(Math.random() * 2),
    });
  }
  return scans;
};

const CONFIG = {
  MIN_EDGE_NET: 0.05,
  MIN_CONFIDENCE: 6,
  KELLY_FRACTION: 0.25,
  MAX_POSITION_PCT: 0.08,
  MAX_SIMULTANEOUS_POSITIONS: 5,
  POLYMARKET_FEE: 0.02,
  MIN_TRADE_SIZE: 5.0,
  CYCLE_INTERVAL: 900,
};

// ─── THEME ──────────────────────────────────────────────────────────────────

const T = {
  bg: "#0a0a0f",
  card: "#12121a",
  cardHover: "#1a1a25",
  border: "#1e1e2e",
  text: "#e2e2e8",
  textMuted: "#6b6b80",
  accent: "#7c5cfc",
  accentDim: "#7c5cfc30",
  green: "#22c55e",
  greenDim: "#22c55e20",
  red: "#ef4444",
  redDim: "#ef444420",
  yellow: "#eab308",
  yellowDim: "#eab30820",
  blue: "#3b82f6",
  blueDim: "#3b82f620",
};

// ─── COMPONENTS ─────────────────────────────────────────────────────────────

const KPI = ({ icon: Icon, label, value, sub, color = T.accent }) => (
  <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: "20px 24px", flex: 1, minWidth: 180 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      <div style={{ background: color + "18", borderRadius: 8, padding: 6, display: "flex" }}>
        <Icon size={16} color={color} />
      </div>
      <span style={{ color: T.textMuted, fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: 1 }}>{label}</span>
    </div>
    <div style={{ fontSize: 28, fontWeight: 700, color: T.text, fontFamily: "monospace" }}>{value}</div>
    {sub && <div style={{ fontSize: 12, color: T.textMuted, marginTop: 4 }}>{sub}</div>}
  </div>
);

const Badge = ({ text, color }) => (
  <span style={{ background: color + "20", color, padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
    {text}
  </span>
);

const TabButton = ({ label, active, onClick, icon: Icon }) => (
  <button
    onClick={onClick}
    style={{
      background: active ? T.accentDim : "transparent",
      border: active ? `1px solid ${T.accent}50` : `1px solid transparent`,
      borderRadius: 8,
      padding: "8px 18px",
      color: active ? T.accent : T.textMuted,
      cursor: "pointer",
      fontSize: 13,
      fontWeight: 600,
      display: "flex",
      alignItems: "center",
      gap: 6,
      transition: "all 0.15s",
    }}
  >
    <Icon size={14} />
    {label}
  </button>
);

const SectionTitle = ({ children }) => (
  <h3 style={{ color: T.text, fontSize: 15, fontWeight: 600, margin: "24px 0 12px", display: "flex", alignItems: "center", gap: 8 }}>
    {children}
  </h3>
);

// ─── TABS ───────────────────────────────────────────────────────────────────

const OverviewTab = ({ trades }) => {
  const resolved = trades.filter((t) => t.status === "won" || t.status === "lost");
  const wins = resolved.filter((t) => t.status === "won");
  const openPositions = trades.filter((t) => t.status === "open");
  const totalPnl = resolved.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const winRate = resolved.length > 0 ? (wins.length / resolved.length) * 100 : 0;
  const avgEdge = trades.length > 0 ? trades.reduce((s, t) => s + t.edge_net, 0) / trades.length : 0;
  const exposure = openPositions.reduce((s, t) => s + t.size_usdc, 0);
  const bankroll = 100;
  const pnl7d = resolved.filter((t) => Date.now() - new Date(t.timestamp).getTime() < 7 * 86400000).reduce((s, t) => s + (t.pnl || 0), 0);
  const circuitBreakerTriggered = pnl7d / bankroll < -0.2;

  const pnlData = resolved
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    .reduce((acc, t) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].cumPnl : 0;
      acc.push({ date: t.date, cumPnl: Math.round((prev + (t.pnl || 0)) * 100) / 100, pnl: t.pnl || 0 });
      return acc;
    }, []);

  return (
    <div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
        <KPI icon={DollarSign} label="P&L Total" value={`${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)} USDC`} sub={`${resolved.length} trades resolved`} color={totalPnl >= 0 ? T.green : T.red} />
        <KPI icon={Target} label="Win Rate" value={`${winRate.toFixed(1)}%`} sub={`${wins.length}W / ${resolved.length - wins.length}L`} color={winRate >= 55 ? T.green : T.yellow} />
        <KPI icon={TrendingUp} label="Avg Edge" value={`${(avgEdge * 100).toFixed(1)}%`} sub={`Min: ${(CONFIG.MIN_EDGE_NET * 100).toFixed(0)}%`} color={T.accent} />
        <KPI icon={Activity} label="Open Positions" value={`${openPositions.length} / ${CONFIG.MAX_SIMULTANEOUS_POSITIONS}`} sub={`${exposure.toFixed(1)} USDC exposure`} color={T.blue} />
        <KPI icon={Shield} label="Circuit Breaker" value={circuitBreakerTriggered ? "TRIGGERED" : "OK"} sub={`7d P&L: ${pnl7d >= 0 ? "+" : ""}${pnl7d.toFixed(2)} USDC`} color={circuitBreakerTriggered ? T.red : T.green} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Cumulative P&L</SectionTitle>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={pnlData}>
              <defs>
                <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.accent} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={T.accent} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke={T.textMuted} fontSize={11} />
              <YAxis stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `$${v}`} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
              <Area type="monotone" dataKey="cumPnl" stroke={T.accent} fill="url(#pnlGrad)" strokeWidth={2} name="Cumulative P&L" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Trade P&L Distribution</SectionTitle>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={pnlData}>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke={T.textMuted} fontSize={10} />
              <YAxis stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `$${v}`} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
              <Bar dataKey="pnl" name="P&L" radius={[4, 4, 0, 0]}>
                {pnlData.map((entry, i) => (
                  <Cell key={i} fill={entry.pnl >= 0 ? T.green : T.red} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

const PositionsTab = ({ trades }) => {
  const openPositions = trades.filter((t) => t.status === "open");
  const recentClosed = trades.filter((t) => t.status === "won" || t.status === "lost").slice(0, 10);

  const TableRow = ({ t, isOpen }) => (
    <tr style={{ borderBottom: `1px solid ${T.border}` }}>
      <td style={{ padding: "10px 12px", fontSize: 13, color: T.text, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.question}</td>
      <td style={{ padding: "10px 8px" }}><Badge text={t.side} color={t.side === "YES" ? T.green : T.red} /></td>
      <td style={{ padding: "10px 8px", fontSize: 13, color: T.text, fontFamily: "monospace" }}>${t.size_usdc}</td>
      <td style={{ padding: "10px 8px", fontSize: 13, color: T.text, fontFamily: "monospace" }}>{t.entry_price}</td>
      <td style={{ padding: "10px 8px", fontSize: 13, color: T.text, fontFamily: "monospace" }}>{(t.edge_net * 100).toFixed(1)}%</td>
      <td style={{ padding: "10px 8px", fontSize: 13, color: T.text }}>{t.confidence}/10</td>
      <td style={{ padding: "10px 8px" }}><Badge text={t.status} color={t.status === "won" ? T.green : t.status === "lost" ? T.red : t.status === "open" ? T.blue : T.textMuted} /></td>
      <td style={{ padding: "10px 8px", fontSize: 13, fontFamily: "monospace", color: t.pnl === null ? T.textMuted : t.pnl >= 0 ? T.green : T.red }}>
        {t.pnl !== null ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}` : "—"}
      </td>
    </tr>
  );

  const TableHead = () => (
    <thead>
      <tr style={{ borderBottom: `1px solid ${T.border}` }}>
        {["Market", "Side", "Size", "Entry", "Edge", "Conf.", "Status", "P&L"].map((h) => (
          <th key={h} style={{ padding: "8px 12px", fontSize: 11, color: T.textMuted, textAlign: "left", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8 }}>{h}</th>
        ))}
      </tr>
    </thead>
  );

  return (
    <div>
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20, marginBottom: 16 }}>
        <SectionTitle><Radio size={16} color={T.green} /> Open Positions ({openPositions.length}/{CONFIG.MAX_SIMULTANEOUS_POSITIONS})</SectionTitle>
        {openPositions.length === 0 ? (
          <p style={{ color: T.textMuted, fontSize: 13, padding: 20, textAlign: "center" }}>No open positions</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <TableHead />
            <tbody>{openPositions.map((t) => <TableRow key={t.id} t={t} isOpen />)}</tbody>
          </table>
        )}
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
        <SectionTitle><Clock size={16} color={T.textMuted} /> Recent Closed</SectionTitle>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <TableHead />
          <tbody>{recentClosed.map((t) => <TableRow key={t.id} t={t} />)}</tbody>
        </table>
      </div>
    </div>
  );
};

const CalibrationTab = ({ trades }) => {
  const resolved = trades.filter((t) => t.status === "won" || t.status === "lost");
  const buckets = [];

  for (let i = 0; i < 10; i++) {
    const low = i / 10;
    const high = (i + 1) / 10;
    const inBucket = resolved.filter((t) => t.agent_probability >= low && t.agent_probability < high);
    if (inBucket.length === 0) continue;
    const predicted = inBucket.reduce((s, t) => s + t.agent_probability, 0) / inBucket.length;
    const actual = inBucket.filter((t) => t.status === "won").length / inBucket.length;
    buckets.push({
      range: `${(low * 100).toFixed(0)}-${(high * 100).toFixed(0)}%`,
      predicted: Math.round(predicted * 100) / 100,
      actual: Math.round(actual * 100) / 100,
      count: inBucket.length,
      error: Math.round(Math.abs(predicted - actual) * 1000) / 1000,
    });
  }

  const avgError = buckets.length > 0 ? buckets.reduce((s, b) => s + b.error, 0) / buckets.length : 0;
  const brier = resolved.length > 0 ? resolved.reduce((s, t) => s + Math.pow(t.agent_probability - (t.status === "won" ? 1 : 0), 2), 0) / resolved.length : 0;

  const perfectLine = [{ x: 0, y: 0 }, { x: 1, y: 1 }];
  const scatterData = buckets.map((b) => ({ x: b.predicted, y: b.actual, count: b.count, range: b.range }));

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <KPI icon={Target} label="Calibration Error" value={`${(avgError * 100).toFixed(1)}%`} sub={`Target: < 8%`} color={avgError < 0.08 ? T.green : T.yellow} />
        <KPI icon={BarChart3} label="Brier Score" value={brier.toFixed(3)} sub="Lower = better (0 = perfect)" color={brier < 0.25 ? T.green : T.yellow} />
        <KPI icon={Activity} label="Resolved Trades" value={resolved.length} sub={`${buckets.length} buckets with data`} color={T.accent} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Predicted vs Actual (Calibration Curve)</SectionTitle>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis type="number" dataKey="x" name="Predicted" domain={[0, 1]} stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <YAxis type="number" dataKey="y" name="Actual" domain={[0, 1]} stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} formatter={(val) => `${(val * 100).toFixed(1)}%`} />
              <ReferenceLine segment={perfectLine} stroke={T.textMuted} strokeDasharray="5 5" label={{ value: "Perfect", fill: T.textMuted, fontSize: 10 }} />
              <Scatter data={scatterData} fill={T.accent} fillOpacity={0.8} r={8} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Error by Bucket</SectionTitle>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={buckets}>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis dataKey="range" stroke={T.textMuted} fontSize={10} />
              <YAxis stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
              <Bar dataKey="error" name="Calibration Error" radius={[4, 4, 0, 0]}>
                {buckets.map((b, i) => (
                  <Cell key={i} fill={b.error < 0.08 ? T.green : b.error < 0.12 ? T.yellow : T.red} fillOpacity={0.8} />
                ))}
              </Bar>
              <ReferenceLine y={0.08} stroke={T.red} strokeDasharray="5 5" label={{ value: "Target 8%", fill: T.red, fontSize: 10, position: "right" }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20, marginTop: 16 }}>
        <SectionTitle>Bucket Details</SectionTitle>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {["Bucket", "Predicted", "Actual", "Error", "Count"].map((h) => (
                <th key={h} style={{ padding: "8px 12px", fontSize: 11, color: T.textMuted, textAlign: "left", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.range} style={{ borderBottom: `1px solid ${T.border}` }}>
                <td style={{ padding: "8px 12px", fontSize: 13, color: T.text }}>{b.range}</td>
                <td style={{ padding: "8px 12px", fontSize: 13, color: T.accent, fontFamily: "monospace" }}>{(b.predicted * 100).toFixed(1)}%</td>
                <td style={{ padding: "8px 12px", fontSize: 13, color: T.text, fontFamily: "monospace" }}>{(b.actual * 100).toFixed(1)}%</td>
                <td style={{ padding: "8px 12px" }}><Badge text={`${(b.error * 100).toFixed(1)}%`} color={b.error < 0.08 ? T.green : b.error < 0.12 ? T.yellow : T.red} /></td>
                <td style={{ padding: "8px 12px", fontSize: 13, color: T.textMuted }}>{b.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const SignalsTab = ({ trades }) => {
  const sorted = [...trades].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const edgeDistribution = trades.map((t) => ({
    question: t.question.slice(0, 30) + "...",
    edge: Math.round(t.edge_net * 1000) / 10,
    confidence: t.confidence,
  }));

  return (
    <div>
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20, marginBottom: 16 }}>
        <SectionTitle>Edge vs Confidence</SectionTitle>
        <ResponsiveContainer width="100%" height={250}>
          <ScatterChart>
            <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
            <XAxis type="number" dataKey="confidence" name="Confidence" domain={[5, 10]} stroke={T.textMuted} fontSize={11} />
            <YAxis type="number" dataKey="edge" name="Edge %" stroke={T.textMuted} fontSize={11} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
            <ReferenceLine x={CONFIG.MIN_CONFIDENCE} stroke={T.yellow} strokeDasharray="5 5" />
            <ReferenceLine y={CONFIG.MIN_EDGE_NET * 100} stroke={T.yellow} strokeDasharray="5 5" />
            <Scatter data={edgeDistribution} fill={T.accent} fillOpacity={0.7} r={6} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
        <SectionTitle>All Signals ({sorted.length})</SectionTitle>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {["Date", "Market", "Side", "Agent P", "Market P", "Edge", "Conf.", "Status", "P&L"].map((h) => (
                <th key={h} style={{ padding: "8px 10px", fontSize: 11, color: T.textMuted, textAlign: "left", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => (
              <tr key={t.id} style={{ borderBottom: `1px solid ${T.border}`, transition: "background 0.1s" }}>
                <td style={{ padding: "8px 10px", fontSize: 12, color: T.textMuted, fontFamily: "monospace" }}>{t.date}</td>
                <td style={{ padding: "8px 10px", fontSize: 12, color: T.text, maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.question}</td>
                <td style={{ padding: "8px 6px" }}><Badge text={t.side} color={t.side === "YES" ? T.green : T.red} /></td>
                <td style={{ padding: "8px 6px", fontSize: 12, color: T.accent, fontFamily: "monospace" }}>{(t.agent_probability * 100).toFixed(1)}%</td>
                <td style={{ padding: "8px 6px", fontSize: 12, color: T.textMuted, fontFamily: "monospace" }}>{(t.market_probability * 100).toFixed(1)}%</td>
                <td style={{ padding: "8px 6px", fontSize: 12, fontFamily: "monospace", color: t.edge_net >= CONFIG.MIN_EDGE_NET ? T.green : T.red }}>{(t.edge_net * 100).toFixed(1)}%</td>
                <td style={{ padding: "8px 6px", fontSize: 12, color: t.confidence >= CONFIG.MIN_CONFIDENCE ? T.text : T.red }}>{t.confidence}</td>
                <td style={{ padding: "8px 6px" }}><Badge text={t.status} color={t.status === "won" ? T.green : t.status === "lost" ? T.red : t.status === "open" ? T.blue : T.textMuted} /></td>
                <td style={{ padding: "8px 6px", fontSize: 12, fontFamily: "monospace", color: t.pnl === null ? T.textMuted : t.pnl >= 0 ? T.green : T.red }}>
                  {t.pnl !== null ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const ScannerTab = ({ scans }) => {
  const totalScanned = scans.reduce((s, sc) => s + sc.markets_scanned, 0);
  const totalOpps = scans.reduce((s, sc) => s + sc.opportunities_found, 0);
  const totalTrades = scans.reduce((s, sc) => s + sc.trades_placed, 0);
  const hitRate = totalScanned > 0 ? (totalOpps / totalScanned) * 100 : 0;

  const recent = scans.slice(-24);

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <KPI icon={Eye} label="Markets Scanned" value={totalScanned} sub={`Last ${scans.length} cycles`} color={T.accent} />
        <KPI icon={Zap} label="Opportunities" value={totalOpps} sub={`${hitRate.toFixed(1)}% hit rate`} color={T.yellow} />
        <KPI icon={CheckCircle} label="Trades Placed" value={totalTrades} sub={`${totalOpps > 0 ? ((totalTrades / totalOpps) * 100).toFixed(0) : 0}% conversion`} color={T.green} />
        <KPI icon={Clock} label="Cycle Interval" value={`${CONFIG.CYCLE_INTERVAL / 60}min`} sub="APScheduler" color={T.blue} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Markets Scanned (last 24 cycles)</SectionTitle>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={recent}>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis dataKey="hour" stroke={T.textMuted} fontSize={9} interval={3} />
              <YAxis stroke={T.textMuted} fontSize={11} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
              <Bar dataKey="markets_scanned" fill={T.accent} fillOpacity={0.6} name="Scanned" radius={[3, 3, 0, 0]} />
              <Bar dataKey="opportunities_found" fill={T.yellow} fillOpacity={0.8} name="Opportunities" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
          <SectionTitle>Trades Placed per Cycle</SectionTitle>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={recent}>
              <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
              <XAxis dataKey="hour" stroke={T.textMuted} fontSize={9} interval={3} />
              <YAxis stroke={T.textMuted} fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12, color: T.text }} />
              <Bar dataKey="trades_placed" fill={T.green} fillOpacity={0.7} name="Trades" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

// ─── MAIN APP ───────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [trades, setTrades] = useState([]);
  const [scans, setScans] = useState([]);
  const [health, setHealth] = useState(null);
  const [apiConnected, setApiConnected] = useState(false);

  const enrichTrades = useCallback((raw) =>
    raw.map((t) => ({
      ...t,
      date: new Date(t.timestamp).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" }),
    })),
  []);

  const enrichScans = useCallback((raw) =>
    raw.map((s) => ({
      ...s,
      hour: new Date(s.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
    })),
  []);

  useEffect(() => {
    let cancelled = false;
    const fetchAll = async () => {
      try {
        const [tradesRes, scansRes, healthRes] = await Promise.all([
          fetch(`${API_BASE}/api/trades`),
          fetch(`${API_BASE}/api/scans`),
          fetch(`${API_BASE}/api/health`),
        ]);
        if (cancelled) return;
        if (tradesRes.ok && scansRes.ok && healthRes.ok) {
          setTrades(enrichTrades(await tradesRes.json()));
          setScans(enrichScans(await scansRes.json()));
          setHealth(await healthRes.json());
          setApiConnected(true);
        } else {
          setTrades(enrichTrades(generateTrades()));
          setScans(enrichScans(generateScans()));
        }
      } catch {
        setTrades(enrichTrades(generateTrades()));
        setScans(enrichScans(generateScans()));
        setApiConnected(false);
      }
    };
    fetchAll();
    const interval = setInterval(fetchAll, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [enrichTrades, enrichScans]);

  const tabs = [
    { id: "overview", label: "Overview", icon: Activity },
    { id: "positions", label: "Positions", icon: DollarSign },
    { id: "calibration", label: "Calibration", icon: Target },
    { id: "signals", label: "Signals", icon: BarChart3 },
    { id: "scanner", label: "Scanner", icon: Eye },
  ];

  return (
    <div style={{ background: T.bg, minHeight: "100vh", color: T.text, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      {/* Header */}
      <div style={{ borderBottom: `1px solid ${T.border}`, padding: "16px 32px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ background: T.accentDim, borderRadius: 10, padding: 8, display: "flex" }}>
            <Activity size={20} color={T.accent} />
          </div>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: T.text }}>Polymarket Agent</h1>
            <span style={{ fontSize: 11, color: T.textMuted }}>AI Trading Dashboard</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Badge text="PAPER MODE" color={T.yellow} />
          <Badge text={apiConnected ? "API LIVE" : "SIMULATED"} color={apiConnected ? T.green : T.textMuted} />
          <span style={{ fontSize: 11, color: T.textMuted, fontFamily: "monospace" }}>v0.1.0</span>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ padding: "12px 32px", borderBottom: `1px solid ${T.border}`, display: "flex", gap: 6 }}>
        {tabs.map((tab) => (
          <TabButton key={tab.id} label={tab.label} icon={tab.icon} active={activeTab === tab.id} onClick={() => setActiveTab(tab.id)} />
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "20px 32px", maxWidth: 1400, margin: "0 auto" }}>
        {activeTab === "overview" && <OverviewTab trades={trades} />}
        {activeTab === "positions" && <PositionsTab trades={trades} />}
        {activeTab === "calibration" && <CalibrationTab trades={trades} />}
        {activeTab === "signals" && <SignalsTab trades={trades} />}
        {activeTab === "scanner" && <ScannerTab scans={scans} />}
      </div>

      {/* Footer */}
      <div style={{ borderTop: `1px solid ${T.border}`, padding: "12px 32px", display: "flex", justifyContent: "space-between", marginTop: 40 }}>
        <span style={{ fontSize: 11, color: T.textMuted }}>
          Thresholds: edge {">"}= {(CONFIG.MIN_EDGE_NET * 100).toFixed(0)}% | conf {">"}= {CONFIG.MIN_CONFIDENCE} | Kelly {CONFIG.KELLY_FRACTION} | max {CONFIG.MAX_SIMULTANEOUS_POSITIONS} positions | fee {(CONFIG.POLYMARKET_FEE * 100).toFixed(0)}%
        </span>
        <span style={{ fontSize: 11, color: T.textMuted }}>
          {apiConnected
            ? `Data: live (${trades.length} trades, ${scans.length} scans) | API: ${API_BASE}`
            : `Data: simulated (${trades.length} trades, ${scans.length} scans) | Start API: python -m dashboard.api`}
        </span>
      </div>
    </div>
  );
}
