import { useState, useCallback } from "react";

const COLORS = {
  navy: "#1B2A4A",
  darkBlue: "#2E75B6",
  teal: "#0D7377",
  purple: "#6A1B9A",
  green: "#1B5E20",
  red: "#B91C1C",
  orange: "#E65100",
  gold: "#F57F17",
  cyan: "#00838F",
  bg: "#0B1120",
  cardBg: "#111827",
  surfaceBg: "#1A2332",
  text: "#E2E8F0",
  muted: "#94A3B8",
  border: "#2D3748",
};

const LAYERS = {
  data: { color: "#3B82F6", label: "Data Layer", icon: "📡" },
  structure: { color: "#8B5CF6", label: "Structure", icon: "🏗️" },
  state: { color: "#06B6D4", label: "State Machine", icon: "🎯" },
  scoring: { color: "#F59E0B", label: "Confluence Scoring", icon: "⚡" },
  execution: { color: "#10B981", label: "Execution", icon: "🔫" },
  management: { color: "#EC4899", label: "Trade Management", icon: "📊" },
  safety: { color: "#EF4444", label: "Safety & Circuit Breakers", icon: "🛡️" },
  velez: { color: "#A855F7", label: "Velez Layers", icon: "📈" },
};

const flowData = {
  sections: [
    {
      id: "data",
      layer: "data",
      title: "1. DATA INGESTION",
      subtitle: "Feeds & Infrastructure",
      nodes: [
        {
          id: "databento",
          title: "DataBento (ES Futures)",
          detail: "Schema shifting: ohlcv-1m → trades + tbbo → mbp-10. Cost-optimized by Predator State.",
          toggles: ["T28"],
        },
        {
          id: "exchange_ws",
          title: "Exchange WebSocket (Crypto)",
          detail: "Free Binance/Bybit feeds. Dual-exchange redundancy. Never pay DataBento for crypto.",
          toggles: [],
        },
        {
          id: "ring_buffer",
          title: "60-Second Ring Buffer",
          detail: "Circular queue storing last 60 seconds of tick data. Near-zero CPU/RAM. Provides instant Order Flow context on POI tap.",
          toggles: [],
        },
        {
          id: "infra_health",
          title: "InfraHealth Monitor",
          detail: "DataBento latency >500ms, broker API >400ms, exchange status, heartbeat timeout >5s → triggers Type C shutdown.",
          toggles: ["T28"],
        },
      ],
    },
    {
      id: "htf",
      layer: "structure",
      title: "2. HTF ANALYSIS",
      subtitle: "Macro Bias & Regime (Weekly/Monthly Cycle)",
      nodes: [
        {
          id: "htf_mapper",
          title: "HTF Structure Mapper",
          detail: "Evaluates Monthly/Weekly/Daily/4H charts. Identifies macro BOS, swing highs/lows, major Order Blocks and FVGs. Determines directional bias.",
          toggles: ["T01"],
        },
        {
          id: "regime_filter",
          title: "Macro Regime Filter",
          detail: "Checks price vs. Weekly 200 SMA & Monthly 200 SMA. If structural bias conflicts with macro regime (e.g., bullish bias but below Weekly 200 SMA), Trend Alignment score downgraded from +2 to +1.",
          toggles: ["T02"],
        },
        {
          id: "synthetic_poi",
          title: "Synthetic MA POI Generator",
          detail: "If Weekly/Monthly 200 SMA falls outside ALL existing POIs, creates a Synthetic watch zone (MA ± 1.5 Daily ATR). Capped at B grade. Requires 20 SMA Halt for entry.",
          toggles: ["T03"],
        },
        {
          id: "event_calendar",
          title: "Economic Event Calendar",
          detail: "Static JSON, updated weekly. CPI, FOMC, NFP, token unlocks. Feeds the Sudden Move Classifier for Type A (scheduled event) detection.",
          toggles: ["T29"],
        },
      ],
    },
    {
      id: "predator",
      layer: "state",
      title: "3. PREDATOR STATE MACHINE",
      subtitle: "Event-Driven Efficiency",
      nodes: [
        {
          id: "scouting",
          title: "State 1: SCOUTING MODE",
          detail: "Low compute. 15m/1H OHLCV only. Maps POIs (Order Blocks, FVGs, session H/L, PDH/PDL). Calculates ATR-based Proximity Halo. Waits for price to approach a POI.",
          toggles: ["T04", "T05"],
          highlight: "green",
        },
        {
          id: "stalking",
          title: "State 2: STALKING MODE",
          detail: "Medium compute. Triggered when price breaches Proximity Halo (POI ± 1.5 × 1m ATR). Switches to 1m OHLCV. Watches for 1m CHOCH/BOS inside HTF POI. Also triggered by Tape Velocity spike (300% above 1hr avg).",
          toggles: ["T06", "T11"],
          highlight: "gold",
        },
        {
          id: "kill_mode",
          title: "State 3: KILL MODE",
          detail: "Maximum compute. Price taps POI + 1m CHOCH begins. Subscribes to DataBento trades (T&S) + mbp-10 (L2). Deep Order Flow analysis: Tape Speed, Delta Tracking, Whale Watching, Absorption Detection.",
          toggles: ["T06", "T07", "T08", "T09"],
          highlight: "red",
        },
      ],
    },
    {
      id: "scoring",
      layer: "scoring",
      title: "4. CONFLUENCE SCORING (14-Point Rubric v2.0)",
      subtitle: "Tier 1: Core SMC + OF (10 pts) → Gate Check → Tier 2: Velez (4 pts)",
      nodes: [
        {
          id: "tier1",
          title: "Tier 1: Core Criteria (10 pts max)",
          detail: "+2 Daily/4H Trend Alignment (modified by Regime Filter) | +2 Major Liquidity Sweep | +1 Fresh POI | +2 1m CHOCH with Displacement | +2 Order Flow Confirmation (CVD divergence + stacked imbalances) | +1 Killzone Timing",
          toggles: ["T01", "T02", "T04", "T05", "T06", "T07", "T10"],
        },
        {
          id: "gate_check",
          title: "⛔ GATE CHECK: Tier 1 ≥ 7?",
          detail: "If Tier 1 score < 7 → Grade C → NO TRADE. This gate ensures the Velez layers can never substitute for the core SMC + Order Flow edge. Even 13/14 total is rejected if Tier 1 is below 7.",
          toggles: [],
          highlight: "red",
        },
        {
          id: "tier2",
          title: "Tier 2: Velez Layers (4 pts max)",
          detail: "+1 20 SMA Halt Confluence (2m 20 SMA within POI) | +1 Flat 200 SMA Confluence (flat 2m 200 SMA within POI) | +1 Elephant Bar Confirmation (wide-range candle, body ≥70%, range ≥1.3× avg) | +1 20 SMA Micro-Trend Alignment (slope + price position)",
          toggles: ["T12", "T13", "T14", "T15", "T16"],
        },
        {
          id: "grading",
          title: "Grade Assignment & Position Sizing",
          detail: "A+ (12-14): Full risk 1.5-2% | A (11): Standard 1.0-1.5% | B (9-10): Half risk 0.5-1.0% | C (<9): NO TRADE. Synthetic MA POIs capped at B grade max. Type B cascades override to 50% of graded risk.",
          toggles: ["T30"],
        },
      ],
    },
    {
      id: "execution",
      layer: "execution",
      title: "5. EXECUTION",
      subtitle: "Entry & Stop Placement",
      nodes: [
        {
          id: "entry_decision",
          title: "Entry Mode Decision",
          detail: "Normal tape speed: Wait for 1m CHOCH close → place limit at 1m FVG (better R:R). Extreme tape speed (V-shape): If absorption + massive delta spike inside POI → fire market order immediately (Fast Move Switch).",
          toggles: ["T11"],
        },
        {
          id: "stop_placement",
          title: "HVN Shield / LVN Moat Stop",
          detail: "Build micro Volume Profile of POI leg. Identify HVN (institutional accumulation) and LVN (vacuum below). Hard SL = Bottom of LVN − (0.5 × 1m ATR). LVN acts as moat; flash wicks unlikely to penetrate. Fallback: 2× 1m ATR stop.",
          toggles: ["T17"],
        },
        {
          id: "oco_bracket",
          title: "Exchange-Native OCO Bracket",
          detail: "EVERY entry sent with OCO bracket: LVN Moat stop + 2R take profit. If bot dies, exchange server holds hard stop. CME: 'Stop with Protection' + 'Market with Protection' order types.",
          toggles: ["T24"],
          highlight: "red",
        },
      ],
    },
    {
      id: "management",
      layer: "management",
      title: "6. TRADE MANAGEMENT",
      subtitle: "Three-Phase Profit & Trail System",
      nodes: [
        {
          id: "phase1",
          title: "Phase 1: Fixed Partial (2R)",
          detail: "Exit 50% at nearest internal liquidity (15m swing high, 1m FVG at 2-2.5R). Move stop to breakeven + 1 tick on remaining 50%. Position is now risk-free.",
          toggles: ["T23"],
          highlight: "green",
        },
        {
          id: "phase2",
          title: "Phase 2: Structural Node Trail (Runner)",
          detail: "Remaining 50% targets macro Draw on Liquidity. Trail stop behind 5m LVN Moats. After each 5m BOS, run Volume Profile on new leg → new HVN/LVN → move trail to new LVN. RBI/GBI Hold Filter prevents exit on single-candle noise. 20 SMA Health Check tightens Tape Failure threshold (80% → 65% delta) if momentum weakens.",
          toggles: ["T19", "T20", "T21"],
        },
        {
          id: "tape_failure",
          title: "Conditional Tape Failure Exit",
          detail: "If price drops into lower quadrant of HVN AND tape shows high velocity + 80% sell delta (or 65% when 20 SMA health check active) → institutional buyers pulled orders → market-exit immediately. Turns 1R loss into ~0.3R loss.",
          toggles: ["T18"],
        },
        {
          id: "phase3",
          title: "Phase 3: Dynamic Climax Exit",
          detail: "At macro target zone, bot re-enters Kill Mode for exit. Watches for Buying Climax (tape speed vertical + delta positive but price stalls = seller absorption) OR Tape Reversal (massive block sell hits bid). 200 SMA Watch Zone: If Weekly/Monthly 200 SMA within 1 ATR of target, triggers exit on absorption alone (lower threshold).",
          toggles: ["T22"],
        },
      ],
    },
    {
      id: "safety",
      layer: "safety",
      title: "7. SAFETY & CIRCUIT BREAKERS",
      subtitle: "RiskOverlord + Sudden Move Classifier (Always Active)",
      nodes: [
        {
          id: "risk_overlord",
          title: "RiskOverlord (Nuclear Flatten)",
          detail: "4 Pillars: Anti-Spam Rate Limiter (3 orders/60s, 10/hr) | Fat Finger Position Limit (hardcoded MAX) | Hard Capital Thresholds (3 consecutive losses OR -2% daily drawdown) | Zombie Data Feed Monitor (>500ms lag). Any breach → Cancel all orders → Market-exit all → os._exit(1) → Manual restart required.",
          toggles: ["T25", "T26", "T27", "T28"],
          highlight: "red",
        },
        {
          id: "sudden_move",
          title: "Sudden Move Classifier (Chameleon Protocol)",
          detail: "Type A (Scheduled Event): News Shield → freeze entries, tighten stops, 3-min cooldown. Type B (Organic Cascade): 50% size, 30s min buffer, absorption + delta flip required. Type C (Infrastructure Degradation): Full shutdown, rely on OCO only. Classification priority: Infrastructure → Calendar → Velocity/Spread → Normal.",
          toggles: ["T29", "T30"],
        },
        {
          id: "nuclear",
          title: "Nuclear Flatten Sequence",
          detail: "1) Cancel all working orders. 2) Market-exit all positions (Net_Position = 0). 3) Execute os._exit(1) — physically terminate process. 4) Requires manual human restart. Triggered by: order spam, fat finger, daily drawdown, 3 consecutive losses, persistent stale data.",
          toggles: [],
          highlight: "red",
        },
      ],
    },
  ],
  connections: [
    { from: "databento", to: "ring_buffer", label: "tick stream" },
    { from: "exchange_ws", to: "ring_buffer", label: "tick stream" },
    { from: "infra_health", to: "sudden_move", label: "Type C trigger" },
    { from: "htf_mapper", to: "regime_filter", label: "bias" },
    { from: "regime_filter", to: "synthetic_poi", label: "MA values" },
    { from: "regime_filter", to: "tier1", label: "modified +2/+1" },
    { from: "event_calendar", to: "sudden_move", label: "Type A trigger" },
    { from: "scouting", to: "stalking", label: "Proximity Halo breached" },
    { from: "stalking", to: "kill_mode", label: "POI tap + CHOCH begins" },
    { from: "kill_mode", to: "tier1", label: "OF data" },
    { from: "tier1", to: "gate_check", label: "Tier 1 score" },
    { from: "gate_check", to: "tier2", label: "≥ 7 → proceed" },
    { from: "tier2", to: "grading", label: "total score" },
    { from: "grading", to: "entry_decision", label: "grade + size" },
    { from: "entry_decision", to: "stop_placement", label: "" },
    { from: "stop_placement", to: "oco_bracket", label: "" },
    { from: "oco_bracket", to: "phase1", label: "position open" },
    { from: "phase1", to: "phase2", label: "50% taken, BE stop" },
    { from: "phase2", to: "phase3", label: "at macro target" },
    { from: "phase2", to: "tape_failure", label: "HVN failing" },
    { from: "risk_overlord", to: "nuclear", label: "breach detected" },
    { from: "sudden_move", to: "kill_mode", label: "modifies behavior" },
  ],
};

const NodeCard = ({ node, layerColor, isSelected, onClick }) => {
  const highlightColors = {
    green: "#059669",
    gold: "#D97706",
    red: "#DC2626",
  };
  const borderColor = node.highlight
    ? highlightColors[node.highlight]
    : layerColor;

  return (
    <div
      onClick={() => onClick(node.id)}
      style={{
        background: isSelected ? `${layerColor}15` : COLORS.cardBg,
        border: `1.5px solid ${isSelected ? borderColor : COLORS.border}`,
        borderLeft: `4px solid ${borderColor}`,
        borderRadius: 10,
        padding: "14px 16px",
        cursor: "pointer",
        transition: "all 0.2s ease",
        position: "relative",
        boxShadow: isSelected
          ? `0 0 20px ${borderColor}25`
          : "0 2px 8px rgba(0,0,0,0.3)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 8,
        }}
      >
        <div
          style={{
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: 13,
            fontWeight: 700,
            color: COLORS.text,
            lineHeight: 1.3,
          }}
        >
          {node.title}
        </div>
        {node.toggles.length > 0 && (
          <div style={{ display: "flex", gap: 3, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {node.toggles.map((t) => (
              <span
                key={t}
                style={{
                  fontSize: 9,
                  fontFamily: "'JetBrains Mono', monospace",
                  background: `${layerColor}30`,
                  color: layerColor,
                  padding: "1px 5px",
                  borderRadius: 4,
                  fontWeight: 600,
                }}
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      {isSelected && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: `1px solid ${COLORS.border}`,
            fontSize: 12,
            lineHeight: 1.6,
            color: COLORS.muted,
            fontFamily: "'Inter', -apple-system, sans-serif",
          }}
        >
          {node.detail}
        </div>
      )}
    </div>
  );
};

const SectionBlock = ({ section, selectedNode, onNodeClick }) => {
  const layer = LAYERS[section.layer];
  return (
    <div
      style={{
        background: COLORS.surfaceBg,
        border: `1px solid ${COLORS.border}`,
        borderRadius: 14,
        padding: 20,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `linear-gradient(90deg, ${layer.color}, ${layer.color}66, transparent)`,
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 20 }}>{layer.icon}</span>
        <div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 14,
              fontWeight: 800,
              color: layer.color,
              letterSpacing: 1.5,
            }}
          >
            {section.title}
          </div>
          <div
            style={{
              fontSize: 11,
              color: COLORS.muted,
              fontFamily: "'Inter', sans-serif",
              marginTop: 2,
            }}
          >
            {section.subtitle}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
        {section.nodes.map((node) => (
          <NodeCard
            key={node.id}
            node={node}
            layerColor={layer.color}
            isSelected={selectedNode === node.id}
            onClick={onNodeClick}
          />
        ))}
      </div>
    </div>
  );
};

const FlowArrow = ({ label, direction = "down", color = COLORS.muted }) => (
  <div
    style={{
      display: "flex",
      flexDirection: direction === "down" ? "column" : "row",
      alignItems: "center",
      gap: 2,
      padding: direction === "down" ? "6px 0" : "0 6px",
    }}
  >
    <div
      style={{
        width: direction === "down" ? 2 : 20,
        height: direction === "down" ? 20 : 2,
        background: `linear-gradient(${direction === "down" ? "to bottom" : "to right"}, ${color}88, ${color})`,
      }}
    />
    {label && (
      <span
        style={{
          fontSize: 9,
          color: `${color}CC`,
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 600,
          letterSpacing: 0.5,
          textAlign: "center",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
    )}
    <div
      style={{
        width: 0,
        height: 0,
        borderLeft: direction === "down" ? "5px solid transparent" : "none",
        borderRight: direction === "down" ? "5px solid transparent" : "none",
        borderTop: direction === "down" ? `8px solid ${color}` : "none",
        borderBottom: direction === "right" ? "5px solid transparent" : "none",
      }}
    />
  </div>
);

const Legend = () => (
  <div
    style={{
      display: "flex",
      flexWrap: "wrap",
      gap: 12,
      padding: "12px 16px",
      background: COLORS.cardBg,
      borderRadius: 10,
      border: `1px solid ${COLORS.border}`,
    }}
  >
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        color: COLORS.muted,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: 1,
        marginRight: 4,
        alignSelf: "center",
      }}
    >
      LAYERS:
    </span>
    {Object.entries(LAYERS).map(([key, val]) => (
      <div
        key={key}
        style={{ display: "flex", alignItems: "center", gap: 5 }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: 3,
            background: val.color,
          }}
        />
        <span
          style={{
            fontSize: 10,
            color: COLORS.text,
            fontFamily: "'Inter', sans-serif",
          }}
        >
          {val.label}
        </span>
      </div>
    ))}
  </div>
);

const ToggleInfo = () => (
  <div
    style={{
      padding: "10px 16px",
      background: `${COLORS.cardBg}`,
      borderRadius: 10,
      border: `1px solid ${COLORS.border}`,
      display: "flex",
      alignItems: "center",
      gap: 8,
    }}
  >
    <span style={{ fontSize: 14 }}>💡</span>
    <span
      style={{
        fontSize: 11,
        color: COLORS.muted,
        fontFamily: "'Inter', sans-serif",
      }}
    >
      Click any node to expand details. Toggle IDs (T01–T30) shown on each node map to the Feature Toggle config file.
    </span>
  </div>
);

export default function FLOFMatrixFlowchart() {
  const [selectedNode, setSelectedNode] = useState(null);

  const handleNodeClick = useCallback((id) => {
    setSelectedNode((prev) => (prev === id ? null : id));
  }, []);

  const sections = flowData.sections;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: COLORS.bg,
        padding: "24px 16px",
        fontFamily: "'Inter', -apple-system, sans-serif",
      }}
    >
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: COLORS.muted,
              letterSpacing: 4,
              marginBottom: 6,
            }}
          >
            FRACTAL LIQUIDITY & ORDER FLOW
          </div>
          <h1
            style={{
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              fontSize: 32,
              fontWeight: 900,
              color: COLORS.text,
              margin: 0,
              letterSpacing: -0.5,
            }}
          >
            FLOF MATRIX
          </h1>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12,
              color: "#3B82F6",
              marginTop: 4,
              letterSpacing: 2,
            }}
          >
            COMPLETE SYSTEM FLOWCHART
          </div>
          <div
            style={{
              width: 60,
              height: 2,
              background: "linear-gradient(90deg, transparent, #3B82F6, transparent)",
              margin: "12px auto 0",
            }}
          />
        </div>

        {/* Legend + Info */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
          <Legend />
          <ToggleInfo />
        </div>

        {/* Main Flow */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
          {/* 1. Data Ingestion */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[0]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <FlowArrow label="feeds tick data & health status" color={LAYERS.data.color} />

          {/* 2. HTF Analysis */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[1]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <FlowArrow label="directional bias + regime + POIs + event calendar" color={LAYERS.structure.color} />

          {/* 3. Predator State Machine */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[2]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <FlowArrow label="Kill Mode activates → begins scoring" color={LAYERS.state.color} />

          {/* 4. Confluence Scoring */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[3]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <FlowArrow label="grade ≥ B → execute trade" color={LAYERS.scoring.color} />

          {/* 5. Execution */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[4]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <FlowArrow label="position open with OCO protection" color={LAYERS.execution.color} />

          {/* 6. Trade Management */}
          <div style={{ width: "100%" }}>
            <SectionBlock
              section={sections[5]}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
            />
          </div>

          <div style={{ height: 12 }} />

          {/* 7. Safety - Full Width Banner */}
          <div
            style={{
              width: "100%",
              background: `linear-gradient(135deg, ${COLORS.surfaceBg}, #1A1520)`,
              border: `2px solid #EF444466`,
              borderRadius: 14,
              padding: 20,
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                height: 3,
                background: `linear-gradient(90deg, #EF4444, #EF444466, transparent)`,
              }}
            />
            <div
              style={{
                position: "absolute",
                top: 8,
                right: 12,
                fontSize: 9,
                fontFamily: "'JetBrains Mono', monospace",
                color: "#EF4444",
                fontWeight: 700,
                letterSpacing: 2,
                background: "#EF444420",
                padding: "2px 8px",
                borderRadius: 4,
              }}
            >
              ALWAYS ACTIVE
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 20 }}>🛡️</span>
              <div>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 14,
                    fontWeight: 800,
                    color: "#EF4444",
                    letterSpacing: 1.5,
                  }}
                >
                  {sections[6].title}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: COLORS.muted,
                    fontFamily: "'Inter', sans-serif",
                    marginTop: 2,
                  }}
                >
                  {sections[6].subtitle}
                </div>
              </div>
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                marginTop: 14,
              }}
            >
              {sections[6].nodes.map((node) => (
                <NodeCard
                  key={node.id}
                  node={node}
                  layerColor="#EF4444"
                  isSelected={selectedNode === node.id}
                  onClick={handleNodeClick}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Footer Stats */}
        <div
          style={{
            marginTop: 28,
            padding: "16px 20px",
            background: COLORS.cardBg,
            borderRadius: 10,
            border: `1px solid ${COLORS.border}`,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 16,
          }}
        >
          {[
            { label: "System Layers", value: "7", color: "#3B82F6" },
            { label: "Components", value: "27", color: "#8B5CF6" },
            { label: "Feature Toggles", value: "30", color: "#06B6D4" },
            { label: "Confluence Points", value: "14", color: "#F59E0B" },
            { label: "Safety Pillars", value: "4", color: "#EF4444" },
            { label: "Move Types", value: "3", color: "#EC4899" },
          ].map((stat) => (
            <div key={stat.label} style={{ textAlign: "center" }}>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 24,
                  fontWeight: 900,
                  color: stat.color,
                }}
              >
                {stat.value}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: COLORS.muted,
                  fontFamily: "'JetBrains Mono', monospace",
                  letterSpacing: 0.5,
                  marginTop: 2,
                }}
              >
                {stat.label}
              </div>
            </div>
          ))}
        </div>

        {/* Document Reference */}
        <div
          style={{
            marginTop: 16,
            padding: "12px 16px",
            background: COLORS.cardBg,
            borderRadius: 10,
            border: `1px solid ${COLORS.border}`,
            textAlign: "center",
          }}
        >
          <div
            style={{
              fontSize: 10,
              color: COLORS.muted,
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: 1,
            }}
          >
            REFERENCE DOCUMENTS
          </div>
          <div
            style={{
              fontSize: 11,
              color: COLORS.text,
              fontFamily: "'Inter', sans-serif",
              marginTop: 6,
              lineHeight: 1.8,
            }}
          >
            Confluence Grading Rubric v2.0 · Sudden Move Policy (Chameleon Protocol) · HTF MA Integration & Feature Toggle System
          </div>
        </div>
      </div>
    </div>
  );
}
