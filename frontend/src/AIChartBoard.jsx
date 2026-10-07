import { useCallback, useEffect, useRef, useState } from "react";

import {
  askRestaurantQuestion,
  getAnalyticsOverview,
  getAssistantCapabilities,
  getInventoryAnalytics,
  getOrderAnalytics,
  getRevenueByCategory,
  getRevenueTrend,
  getTopDishesAnalytics,
  getWastageAnalytics,
} from "./api";

import { formatMoney } from "./money";

// ============================================================
// PHASE 5 - AI ANALYTICS / CHART BOARD
//
// Every figure on this page comes from an admin analytics endpoint. The
// component holds no revenue, sales, dish, waste or stock number of its
// own, and there is no fallback data behind an error: if a request fails
// the card says so and shows nothing. Swapping in invented numbers here
// would be the one thing this page must never do.
//
// Charts are plain SVG rather than a charting library. The project has no
// chart dependency and adding one for eight fixed shapes would be a large
// install for very little, so the shapes are drawn directly and scale
// with the viewBox.
// ============================================================

const RANGE_OPTIONS = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last_7_days", label: "Last 7 days" },
  { key: "last_30_days", label: "Last 30 days" },
  { key: "all_time", label: "All time" },
];

const LIFECYCLE_ORDER = [
  "Placed",
  "Confirmed",
  "Preparing",
  "Ready",
  "Served",
];

// ============================================================
// SVG CHART PRIMITIVES
// ============================================================

/**
 * A line chart over the series the API returned.
 *
 * `points` is a list of { label, value }. Nothing is generated here: an
 * empty series renders the empty state rather than a flat line that
 * looks like real activity.
 */
function LineChart({ points, valueFormat, ariaLabel }) {
  if (!points || points.length === 0) {
    return <ChartEmpty>No data for this period.</ChartEmpty>;
  }

  const width = 640;
  const height = 220;
  const padLeft = 56;
  const padRight = 12;
  const padTop = 14;
  const padBottom = 30;

  const innerWidth = width - padLeft - padRight;
  const innerHeight = height - padTop - padBottom;

  const values = points.map((point) => Number(point.value) || 0);
  const maxValue = Math.max(...values, 0);
  const minValue = Math.min(...values, 0);

  // A flat series would divide by zero; give it a nominal ceiling so the
  // line sits mid-chart instead of collapsing onto the axis.
  const span = maxValue - minValue || 1;

  const stepX =
    points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const toX = (index) => padLeft + stepX * index;
  const toY = (value) =>
    padTop + innerHeight - ((Number(value) - minValue) / span) * innerHeight;

  const line = points
    .map((point, index) => `${toX(index)},${toY(point.value)}`)
    .join(" ");

  const area =
    points.length > 0
      ? `${padLeft},${padTop + innerHeight} ${line} ${toX(points.length - 1)},${
          padTop + innerHeight
        }`
      : "";

  // Label every axis on a short series, otherwise thin them out so the
  // dates do not overlap on a phone.
  const labelEvery = Math.max(1, Math.ceil(points.length / 7));

  return (
    <svg
      className="ai-svg-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
        const y = padTop + innerHeight * fraction;

        return (
          <g key={fraction}>
            <line
              x1={padLeft}
              y1={y}
              x2={width - padRight}
              y2={y}
              className="ai-grid-line"
            />
            <text x={padLeft - 8} y={y + 4} className="ai-axis-label" textAnchor="end">
              {valueFormat(maxValue - span * fraction)}
            </text>
          </g>
        );
      })}

      {points.length > 1 && <polygon points={area} className="ai-chart-area" />}

      <polyline points={line} className="ai-chart-line" />

      {points.map((point, index) => (
        <circle
          key={`${point.label}-${index}`}
          cx={toX(index)}
          cy={toY(point.value)}
          r={points.length > 20 ? 2.5 : 3.5}
          className="ai-chart-dot"
        >
          <title>{`${point.label}: ${valueFormat(point.value)}`}</title>
        </circle>
      ))}

      {points.map((point, index) =>
        index % labelEvery === 0 || index === points.length - 1 ? (
          <text
            key={`label-${point.label}-${index}`}
            x={toX(index)}
            y={height - 9}
            className="ai-axis-label"
            textAnchor="middle"
          >
            {point.label}
          </text>
        ) : null
      )}
    </svg>
  );
}

/**
 * A horizontal bar chart, used where the category labels are words
 * (dish names, statuses) and would be unreadable on an x axis.
 */
function BarChart({ points, valueFormat, ariaLabel }) {
  if (!points || points.length === 0) {
    return <ChartEmpty>No data available.</ChartEmpty>;
  }

  const width = 640;
  const rowHeight = 34;
  const height = points.length * rowHeight + 12;
  const labelWidth = 210;
  const valueWidth = 78;
  const barArea = width - labelWidth - valueWidth;

  const maxValue = Math.max(...points.map((p) => Number(p.value) || 0), 0);

  return (
    <svg
      className="ai-svg-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel}
    >
      {points.map((point, index) => {
        const value = Number(point.value) || 0;

        // A zero bar renders as a hairline so the row is still visible
        // and clearly reads as zero rather than missing.
        const barWidth = maxValue > 0 ? Math.max(2, (value / maxValue) * barArea) : 2;
        const y = index * rowHeight + 6;

        return (
          <g key={`${point.label}-${index}`}>
            <text x={labelWidth - 10} y={y + 15} className="ai-bar-label" textAnchor="end">
              {truncate(point.label, 26)}
            </text>

            <rect
              x={labelWidth}
              y={y}
              width={barWidth}
              height={20}
              rx={4}
              className="ai-chart-bar"
            />

            <text x={labelWidth + barWidth + 8} y={y + 15} className="ai-bar-value">
              {valueFormat(value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** A donut, used for the inventory and payment splits. */
function DonutChart({ points, ariaLabel }) {
  const total = points.reduce((sum, point) => sum + (Number(point.value) || 0), 0);

  if (!points.length || total <= 0) {
    return <ChartEmpty>No data available.</ChartEmpty>;
  }

  const size = 200;
  const radius = 74;
  const circumference = 2 * Math.PI * radius;

  // Segment offsets are derived with a running sum rather than by
  // mutating a counter inside the render pass, so the chart stays a pure
  // function of its props.
  const segments = points.reduce((accumulated, point) => {
    const value = Number(point.value) || 0;

    const offset = accumulated.running;

    accumulated.running += (value / total) * circumference;

    accumulated.segments.push({
      label: point.label,
      value,
      dash: (value / total) * circumference,
      offset,
    });

    return accumulated;
  }, { running: 0, segments: [] });

  return (
    <div className="ai-donut-wrap">
      <svg
        className="ai-svg-donut"
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={ariaLabel}
      >
        {segments.segments.map((segment, index) => (
          <circle
            key={segment.label}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            className={`ai-donut-segment seg-${index}`}
            strokeDasharray={`${segment.dash} ${circumference - segment.dash}`}
            strokeDashoffset={-segment.offset}
          >
            <title>{`${segment.label}: ${segment.value}`}</title>
          </circle>
        ))}

        <text x={size / 2} y={size / 2 - 2} className="ai-donut-total" textAnchor="middle">
          {total}
        </text>
        <text x={size / 2} y={size / 2 + 16} className="ai-donut-caption" textAnchor="middle">
          total
        </text>
      </svg>

      <ul className="ai-donut-legend">
        {points.map((point, index) => (
          <li key={point.label}>
            <span className={`ai-legend-swatch seg-${index}`} />
            <span className="ai-legend-label">{point.label}</span>
            <strong>{point.value}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChartEmpty({ children }) {
  return <div className="ai-chart-empty">{children}</div>;
}

function truncate(text, max) {
  const value = String(text ?? "");

  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/**
 * A chart card with consistent loading, error and empty handling.
 *
 * The three states are deliberately distinct: an empty dataset says
 * "no data", a failure says "could not load", and neither ever falls
 * back to sample numbers.
 */
function ChartCard({ title, subtitle, loading, error, hasData, children }) {
  return (
    <section className="ai-chart-card">
      <header className="ai-chart-card-head">
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
      </header>

      {loading && <div className="ai-chart-placeholder">Loading…</div>}

      {!loading && error && (
        <div className="ai-chart-error">
          Could not load this data. {error}
        </div>
      )}

      {!loading && !error && !hasData && (
        <ChartEmpty>
          No data recorded for the selected period.
        </ChartEmpty>
      )}

      {!loading && !error && hasData && children}
    </section>
  );
}

// ============================================================
// PHASE 6B - CONVERSATION UI
//
// One free-text box. No category picker, no intent list, no report
// buttons. The whole point of this phase is that the admin should not
// have to know which questions are supported, so the interface must not
// tell them either.
//
// The answer is rendered as labelled sections rather than one paragraph,
// because the server separates them for a reason: `key_numbers` and
// `observations` are measurements, `inference` is a reading of them, and
// `recommendations` is advice. Collapsing that into one block would lose
// the distinction the backend was careful to make.
//
// Nothing here formats a figure. Every number arrives from the server and
// is displayed as received.
// ============================================================

/**
 * A single labelled section of an answer.
 *
 * `tone` only changes the accent colour; the wording that tells the
 * reader what kind of claim they are looking at comes from the server.
 */
function AnswerSection({ label, lines, tone = "fact", empty }) {
  if (!lines || lines.length === 0) {
    return empty ? <p className="ops-answer-empty">{empty}</p> : null;
  }

  return (
    <section className={`ops-section ops-section-${tone}`}>
      <h4>{label}</h4>
      <ul>
        {lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The provenance strip under an answer.
 *
 * Shows the period the answer describes and the data sources that
 * actually contributed. Sources that returned nothing are shown
 * separately, so an answer built from two of six sources cannot look
 * equally grounded in all six.
 */
function AnswerProvenance({ answer }) {
  const window_ = answer.window;
  const sources = answer.data_sources || [];
  const missing = answer.tools_without_data || [];

  if (!window_ && sources.length === 0 && missing.length === 0) {
    return null;
  }

  return (
    <div className="ops-provenance">
      {window_ && (
        <p className="ops-provenance-window">
          Period read:{" "}
          <strong>
            {window_.start_date} to {window_.end_date}
          </strong>{" "}
          ({window_.label})
          {window_.inherited && (
            <em> — carried over from your previous question</em>
          )}
        </p>
      )}

      {sources.length > 0 && (
        <details className="ops-provenance-details">
          <summary>
            Read from {sources.length} data source
            {sources.length === 1 ? "" : "s"}
          </summary>
          <ul className="ops-source-list">
            {sources.map((source) => (
              <li key={source.tool}>
                <strong>{source.domain}</strong> — {source.description}
              </li>
            ))}
          </ul>
        </details>
      )}

      {missing.length > 0 && (
        <p className="ops-provenance-missing">
          {missing.length} data source{missing.length === 1 ? "" : "s"}{" "}
          returned nothing for this period: {missing.join(", ")}.
        </p>
      )}
    </div>
  );
}

/**
 * One exchange in the conversation.
 *
 * Questions and answers are kept in component state for the life of the
 * page. Nothing is persisted, and closing the tab ends the conversation -
 * which matches the server, which holds no conversation either.
 */
function ConversationTurn({ turn }) {
  return (
    <article className="ops-turn">
      <div className="ops-question">
        <span className="ops-question-label">You asked</span>
        <p>{turn.question}</p>
      </div>

      <div
        className={`ops-answer ${
          turn.answer.answered ? "" : "ops-answer-nodata"
        }`}
      >
        {turn.pending ? (
          <p className="ops-pending">Reading the restaurant data…</p>
        ) : (
          <>
            {turn.answer.conclusion && (
              <p className="ops-conclusion">{turn.answer.conclusion}</p>
            )}

            <AnswerSection
              label="Key numbers"
              lines={turn.answer.key_numbers}
              tone="fact"
            />

            <AnswerSection
              label="Observations"
              lines={turn.answer.observations}
              tone="fact"
            />

            <AnswerSection
              label="What the data suggests"
              lines={turn.answer.inference}
              tone="inference"
            />

            <AnswerSection
              label="Recommendations"
              lines={turn.answer.recommendations}
              tone="recommend"
            />

            <AnswerSection
              label="What could not be answered"
              lines={turn.answer.limitations}
              tone="limit"
            />

            <AnswerProvenance answer={turn.answer} />
          </>
        )}
      </div>
    </article>
  );
}

// ============================================================
// PAGE
// ============================================================

function AIChartBoard() {
  const [range, setRange] = useState("last_7_days");

  const [overview, setOverview] = useState(null);
  const [revenueTrend, setRevenueTrend] = useState(null);
  const [topDishes, setTopDishes] = useState(null);
  const [categoryRevenue, setCategoryRevenue] = useState(null);
  const [wastage, setWastage] = useState(null);
  const [inventory, setInventory] = useState(null);
  const [orderStats, setOrderStats] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Assistant. `context` is the server's conversation memory; `turns` is
  // the visible transcript.
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [context, setContext] = useState(null);
  const [asking, setAsking] = useState(false);
  const [answerError, setAnswerError] = useState("");
  const [capabilityCount, setCapabilityCount] = useState(null);

  const transcriptRef = useRef(null);

  // Each panel records its own failure so one broken endpoint does not
  // blank the whole board.
  const [failures, setFailures] = useState({});

  // Declared before the effect that calls it, and memoised so the effect
  // can depend on it honestly. Previously it was referenced from an
  // effect declared above it, which the hooks lint flags as an access
  // before declaration.
  const loadBoard = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      setFailures({});

      // Each panel settles independently: a partial outage still shows
      // whatever did load, and the broken card names itself.
      const results = await Promise.allSettled([
        getAnalyticsOverview(),
        getRevenueTrend(range),
        getTopDishesAnalytics(5, range),
        getRevenueByCategory(range),
        getWastageAnalytics(range === "today" ? "last_30_days" : range),
        getInventoryAnalytics(),
        getOrderAnalytics(),
      ]);

      const keys = [
        "overview",
        "revenueTrend",
        "topDishes",
        "categoryRevenue",
        "wastage",
        "inventory",
        "orderStats",
      ];

      const nextFailures = {};

      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          return;
        }

        nextFailures[keys[index]] =
          result.reason?.response?.data?.detail ||
          result.reason?.message ||
          "Request failed";
      });

      setFailures(nextFailures);

      if (results[0].status === "fulfilled") setOverview(results[0].value);
      if (results[1].status === "fulfilled") setRevenueTrend(results[1].value);
      if (results[2].status === "fulfilled") setTopDishes(results[2].value);
      if (results[3].status === "fulfilled") setCategoryRevenue(results[3].value);
      if (results[4].status === "fulfilled") setWastage(results[4].value);
      if (results[5].status === "fulfilled") setInventory(results[5].value);
      if (results[6].status === "fulfilled") setOrderStats(results[6].value);

      if (results.every((result) => result.status === "rejected")) {
        setError("Could not reach the analytics service.");
      }
    } finally {
      setLoading(false);
    }
    // `range` is a real dependency: the Refresh button calls this
    // directly, so it must always close over the range currently
    // selected rather than the one captured when it was first created.
  }, [range]);

  useEffect(() => {
    loadBoard();
  }, [loadBoard]);

  useEffect(() => {
    getAssistantCapabilities()
      .then((data) => setCapabilityCount(data.count ?? null))
      .catch(() => setCapabilityCount(null));
  }, []);

  // Keep the newest answer in view as the transcript grows.
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [turns]);

  const submitQuestion = async (event) => {
    event?.preventDefault?.();

    const trimmed = question.trim();

    if (!trimmed || asking) {
      return;
    }

    // A placeholder turn is appended first so the UI shows the pending
    // state against the right question. The server decides whether it can
    // answer; nothing is formatted here.
    const pendingTurn = {
      question: trimmed,
      pending: true,
      answer: { answered: false, key_numbers: [], observations: [] },
    };

    setTurns((previous) => [...previous, pendingTurn]);
    setQuestion("");
    setAsking(true);
    setAnswerError("");

    try {
      const data = await askRestaurantQuestion(trimmed, context);

      setContext(data.context ?? null);

      setTurns((previous) =>
        previous.map((turn, index) =>
          index === previous.length - 1
            ? { question: trimmed, pending: false, answer: data }
            : turn
        )
      );
    } catch (err) {
      setTurns((previous) =>
        previous.slice(0, previous.length - 1)
      );

      setAnswerError(
        err.response?.data?.detail || "Could not reach the assistant."
      );
    } finally {
      setAsking(false);
    }
  };

  const startNewQuestion = () => {
    setTurns([]);
    setContext(null);
    setAnswerError("");
  };

  const moneyFormat = (value) => formatMoney(value || 0);
  const countFormat = (value) => String(Math.round(Number(value) || 0));

  const revenuePoints = (revenueTrend?.data || []).map((point) => ({
    label: point.date.slice(5),
    value: point.revenue,
  }));

  const orderPoints = (revenueTrend?.data || []).map((point) => ({
    label: point.date.slice(5),
    value: point.orders,
  }));

  const dishPoints = (topDishes?.top_dishes || []).map((dish) => ({
    label: dish.dish,
    value: dish.quantity_sold,
  }));

  const categoryPoints = (categoryRevenue?.categories || []).map((slice) => ({
    label: slice.category,
    value: slice.revenue,
  }));

  const wastagePoints = (wastage?.trend || []).map((point) => ({
    label: point.date.slice(5),
    value: point.cost,
  }));

  const lifecyclePoints = LIFECYCLE_ORDER.map((status) => ({
    label: status,
    value: orderStats?.lifecycle?.[status] ?? 0,
  }));

  const paymentPoints = Object.entries(orderStats?.payment || {}).map(
    ([status, count]) => ({ label: status, value: count })
  );

  const inventoryPoints = [
    { label: "Available", value: inventory?.available_count ?? 0 },
    { label: "Low stock", value: inventory?.low_stock_count ?? 0 },
    { label: "Out of stock", value: inventory?.out_of_stock_count ?? 0 },
  ];

  return (
    <div className="page-container ai-board-page">
      <div className="page-header">
        <div>
          <h1>AI Analytics</h1>
          <p>
            Real figures read from the restaurant database. Nothing on this
            page is estimated or filled in.
          </p>
        </div>

        <button className="secondary-btn" onClick={loadBoard} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {/* ============================================================
          AI OPERATIONS ASSISTANT

          Free text only. There is no category picker and no list of
          supported questions: the admin should not have to know which
          questions exist, and the interface should not imply that they
          would have to.
          ============================================================ */}
      <section className="ai-assistant-card ops-assistant">
        <div className="ai-assistant-head">
          <h2>✦ Paradise AI Assistant</h2>
          <p>
            Ask anything about your restaurant. Every figure below is read
            from the database at the moment you ask — sales, orders, bills,
            payments, guests, menu, bookings, tables, kitchen, stock, waste,
            reviews or anything else the records cover. Where something is
            not recorded, it says so instead of estimating.
          </p>
        </div>

        <form className="ai-assistant-form" onSubmit={submitQuestion}>
          <input
            type="text"
            className="ai-assistant-input"
            placeholder="Ask anything about your restaurant…"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            aria-label="Ask anything about your restaurant"
            maxLength={500}
          />
          <button type="submit" className="primary-btn" disabled={asking}>
            {asking ? "Reading…" : "Ask"}
          </button>
        </form>

        {turns.length > 0 && (
          <div className="ops-transcript-head">
            <span>
              {turns.length} question{turns.length === 1 ? "" : "s"} this
              session
            </span>
            <button
              type="button"
              className="ops-clear-btn"
              onClick={startNewQuestion}
            >
              Start a new conversation
            </button>
          </div>
        )}

        {answerError && <div className="error-message">{answerError}</div>}

        <div className="ops-transcript" ref={transcriptRef}>
          {turns.length === 0 ? (
            <p className="ops-transcript-intro">
              Ask in your own words. “Why did sales drop?”, “what should I
              prepare more of?”, “which areas need attention?” and “how are
              the delivered orders doing?” all work. A follow-up like
              “what about the previous week?” keeps the same subject.
              {capabilityCount !== null && (
                <>
                  {" "}
                  This assistant can read{" "}
                  <strong>{capabilityCount}</strong> kinds of restaurant
                  data and chooses between them itself.
                </>
              )}
            </p>
          ) : (
            turns.map((turn, index) => (
              <ConversationTurn key={index} turn={turn} />
            ))
          )}
        </div>
      </section>

      {/* ============================================================
          OVERVIEW TILES
          ============================================================ */}
      {overview && (
        <div className="stats-grid ai-stat-grid">
          <div className="stat-card">
            <h3>Today&apos;s Revenue</h3>
            <strong>{formatMoney(overview.today.revenue)}</strong>
            <small>
              {overview.revenue_change_percent === null ||
              overview.revenue_change_percent === undefined
                ? "No comparable figure yesterday"
                : `${overview.revenue_change_percent}% vs yesterday`}
            </small>
          </div>

          <div className="stat-card">
            <h3>Today&apos;s Orders</h3>
            <strong>{overview.today.orders}</strong>
            <small>{overview.today.portions_sold} portions sold</small>
          </div>

          <div className="stat-card">
            <h3>Average Order Value</h3>
            <strong>{formatMoney(overview.today.average_order_value)}</strong>
            <small>across today&apos;s orders</small>
          </div>

          <div className="stat-card">
            <h3>Today&apos;s Wastage</h3>
            <strong>{formatMoney(overview.today.wastage_cost)}</strong>
            <small>{overview.today.wastage_entries} recorded items</small>
          </div>

          <div className="stat-card">
            <h3>Low Stock Items</h3>
            <strong>{overview.inventory.low_stock}</strong>
            <small>
              {overview.inventory.out_of_stock} out of stock ·{" "}
              {overview.inventory.available} available
            </small>
          </div>

          {/* Food status and payment are separate facts. This tile never
              implies that a served order has been paid. */}
          <div className="stat-card ai-stat-warn">
            <h3>Served &amp; Unpaid</h3>
            <strong>{overview.unpaid_served_orders}</strong>
            <small>
              {overview.served_orders} served ·{" "}
              {overview.payment?.paid ?? 0} paid
            </small>
          </div>
        </div>
      )}

      {/* ============================================================
          RANGE SELECTOR
          ============================================================ */}
      <div className="ai-range-row">
        {RANGE_OPTIONS.map((option) => (
          <button
            key={option.key}
            className={`ai-range-chip ${range === option.key ? "active" : ""}`}
            onClick={() => setRange(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* ============================================================
          CHART BOARD
          ============================================================ */}
      <div className="ai-chart-grid">
        <ChartCard
          title="Revenue Trend"
          subtitle={
            revenueTrend
              ? `${formatMoney(revenueTrend.total_revenue)} over ${revenueTrend.days} days`
              : ""
          }
          loading={loading}
          error={failures.revenueTrend}
          hasData={revenueTrend?.has_data}
        >
          <LineChart
            points={revenuePoints}
            valueFormat={moneyFormat}
            ariaLabel="Revenue by day"
          />
        </ChartCard>

        <ChartCard
          title="Orders Trend"
          subtitle={
            revenueTrend
              ? `${revenueTrend.total_orders} orders over ${revenueTrend.days} days`
              : ""
          }
          loading={loading}
          error={failures.revenueTrend}
          hasData={revenueTrend?.has_data}
        >
          <LineChart
            points={orderPoints}
            valueFormat={countFormat}
            ariaLabel="Orders by day"
          />
        </ChartCard>

        <ChartCard
          title="Top Selling Dishes"
          subtitle="By portions actually sold"
          loading={loading}
          error={failures.topDishes}
          hasData={topDishes?.has_data}
        >
          <BarChart
            points={dishPoints}
            valueFormat={countFormat}
            ariaLabel="Top selling dishes by quantity"
          />
        </ChartCard>

        <ChartCard
          title="Revenue by Category"
          subtitle="Real revenue per menu category"
          loading={loading}
          error={failures.categoryRevenue}
          hasData={categoryRevenue?.has_data}
        >
          <BarChart
            points={categoryPoints}
            valueFormat={moneyFormat}
            ariaLabel="Revenue by category"
          />
        </ChartCard>

        <ChartCard
          title="Food Wastage Trend"
          subtitle="Recorded wastage cost per day"
          loading={loading}
          error={failures.wastage}
          hasData={wastage?.has_data}
        >
          <LineChart
            points={wastagePoints}
            valueFormat={moneyFormat}
            ariaLabel="Wastage cost by day"
          />
        </ChartCard>

        <ChartCard
          title="Inventory Status"
          subtitle="Counted against each item's minimum stock"
          loading={loading}
          error={failures.inventory}
          hasData={inventory?.has_data}
        >
          <DonutChart
            points={inventoryPoints}
            ariaLabel="Inventory status split"
          />
        </ChartCard>

        <ChartCard
          title="Order Lifecycle"
          subtitle="Live order status counts"
          loading={loading}
          error={failures.orderStats}
          hasData={orderStats?.has_data}
        >
          <BarChart
            points={lifecyclePoints}
            valueFormat={countFormat}
            ariaLabel="Orders by lifecycle status"
          />
        </ChartCard>

        {/* Payment is charted from payment_status alone. A served order
            appearing here as "unpaid" is expected, not an error. */}
        <ChartCard
          title="Payment Status"
          subtitle="Tracked independently of food status"
          loading={loading}
          error={failures.orderStats}
          hasData={orderStats?.has_data}
        >
          <DonutChart
            points={
              paymentPoints.length > 0
                ? paymentPoints
                : [{ label: "No payment data", value: 0 }]
            }
            ariaLabel="Payment status split"
          />
        </ChartCard>
      </div>
    </div>
  );
}

export default AIChartBoard;
