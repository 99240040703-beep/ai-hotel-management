import React, { useEffect, useState } from "react";
import {
 getAIInsights,
 getFoodRecommendations,
 getPopularDishes,
 classifySentiment,
 getSentimentSummary,
 getDemandForecast,
 getRevenueForecast,
 getWasteAnalysisAI,
 getDynamicPricing,
 updateMenuPriceByName,
} from "./api";
import { formatMoney } from "./money";

function AIInsights() {
 const [activeModule, setActiveModule] = useState("overview"); // overview, recommender, sentiment, demand, revenue, waste, pricing
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");

 // Data states
 const [overviewData, setOverviewData] = useState(null);
 const [customersList] = useState([
 "Priya",
 "Arjun",
 "Meena",
 "Karthik",
 "Divya",
 "Rahul",
 ]);
 const [selectedCustomer, setSelectedCustomer] = useState("Priya");
 const [customerRecs, setCustomerRecs] = useState(null);
 const [popularDishes, setPopularDishes] = useState([]);

 // Sentiment
 const [sentimentSummary, setSentimentSummary] = useState(null);
 const [sandboxText, setSandboxText] = useState(
 "The biryani was sensational, aromatic and authentic with rapid service!"
 );
 const [sandboxResult, setSandboxResult] = useState(null);
 const [analyzingSandbox, setAnalyzingSandbox] = useState(false);

 // Demand & Revenue
 const [demandData, setDemandData] = useState(null);
 const [revenueData, setRevenueData] = useState(null);

 // Waste
 const [wasteData, setWasteData] = useState(null);

 // Dynamic Pricing
 const [pricingData, setPricingData] = useState(null);
 const [applyingPriceItem, setApplyingPriceItem] = useState(null);
 const [priceSuccessMsg, setPriceSuccessMsg] = useState("");

 useEffect(() => {
 loadAllAIData();
 }, []);

 const loadAllAIData = async () => {
 try {
 setLoading(true);
 setError("");

 const [
 insightsRes,
 popDishesRes,
 recRes,
 sentRes,
 demandRes,
 revRes,
 wasteRes,
 pricingRes,
 ] = await Promise.allSettled([
 getAIInsights(),
 getPopularDishes(5),
 getFoodRecommendations(selectedCustomer, 5),
 getSentimentSummary(),
 getDemandForecast(7, 6),
 getRevenueForecast(7),
 getWasteAnalysisAI(),
 getDynamicPricing(),
 ]);

 if (insightsRes.status === "fulfilled") setOverviewData(insightsRes.value);
 if (popDishesRes.status === "fulfilled")
 setPopularDishes(popDishesRes.value?.popular_dishes || []);
 if (recRes.status === "fulfilled") setCustomerRecs(recRes.value);
 if (sentRes.status === "fulfilled") setSentimentSummary(sentRes.value);
 if (demandRes.status === "fulfilled") setDemandData(demandRes.value);
 if (revRes.status === "fulfilled") setRevenueData(revRes.value);
 if (wasteRes.status === "fulfilled") setWasteData(wasteRes.value);
 if (pricingRes.status === "fulfilled") setPricingData(pricingRes.value);
 } catch (err) {
 console.error("Error loading AI modules data:", err);
 setError("Failed to load some AI/ML modules. Ensure backend is running.");
 } finally {
 setLoading(false);
 }
 };

 // Re-fetch customer recommendations when dropdown changes
 const handleCustomerChange = async (name) => {
 setSelectedCustomer(name);
 try {
 const res = await getFoodRecommendations(name, 5);
 setCustomerRecs(res);
 } catch (err) {
 console.error("Error getting customer recommendations:", err);
 }
 };

 // Test custom text in NLP Sentiment Sandbox
 const handleAnalyzeSandbox = async () => {
 if (!sandboxText.trim()) return;
 try {
 setAnalyzingSandbox(true);
 const res = await classifySentiment(sandboxText);
 setSandboxResult(res);
 } catch (err) {
 console.error("Sandbox NLP error:", err);
 } finally {
 setAnalyzingSandbox(false);
 }
 };

 // Apply Dynamic Price to live menu
 const handleApplyPrice = async (item) => {
 try {
 setApplyingPriceItem(item.menu_item);
 setPriceSuccessMsg("");
 await updateMenuPriceByName(item.menu_item, item.suggested_price);

 setPriceSuccessMsg(
 ` Updated price for "${item.menu_item}"from ${formatMoney(
 item.current_price,
 )} to ${formatMoney(item.suggested_price)} in live menu database!`
 );

 // Refresh pricing list
 const freshPricing = await getDynamicPricing();
 setPricingData(freshPricing);
 } catch (err) {
 console.error("Error applying price:", err);
 alert("Failed to update menu price.");
 } finally {
 setApplyingPriceItem(null);
 }
 };

 if (loading) {
 return (
 <div className="page-container">
 <div className="ai-loading-box">
 <div className="ai-spinner"></div>
 <h2>Processing AI & Machine Learning Decision Engine...</h2>
 <p>Analyzing historical orders, sentiment NLP vectors, and predictive models.</p>
 </div>
 </div>
 );
 }

 return (
 <div className="page-container ai-decision-support-page">
 {/* Top Header */}
 <div className="page-header">
 <div>
 <span className="ai-kicker">DECISION SUPPORT SYSTEM (SLIDE 9)</span>
 <h1>AI & Machine Learning Engine</h1>
 <p>
 Integrated operational intelligence powering recommendations, forecasting, NLP, and dynamic pricing.
 </p>
 </div>

 <button className="secondary-btn"onClick={loadAllAIData}>
 Refresh All AI Models
 </button>
 </div>

 {error && <div className="error-message">{error}</div>}

 {/* Module Selector Navigation Tabs */}
 <div className="ai-module-nav">
 <button
 className={activeModule === "overview" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("overview")}
 >
 Executive Overview
 </button>
 <button
 className={activeModule === "recommender" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("recommender")}
 >
 1. Food Recommendation
 </button>
 <button
 className={activeModule === "sentiment" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("sentiment")}
 >
 2. Sentiment Analysis
 </button>
 <button
 className={activeModule === "demand" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("demand")}
 >
 3. Demand Prediction
 </button>
 <button
 className={activeModule === "revenue" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("revenue")}
 >
 4. Revenue Prediction
 </button>
 <button
 className={activeModule === "waste" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("waste")}
 >
 5. Waste Analysis
 </button>
 <button
 className={activeModule === "pricing" ? "ai-tab active" : "ai-tab"}
 onClick={() =>setActiveModule("pricing")}
 >
 6. Dynamic Pricing
 </button>
 </div>

 {/* =========================================================
 MODULE 0: EXECUTIVE OVERVIEW
 ========================================================= */}
 {activeModule === "overview" && overviewData && (
 <div className="ai-tab-content">
 {/* Top KPI Cards */}
 <div className="stats-grid">
 <div className="stat-card">
 <h3>Recorded Revenue</h3>
 <strong>{formatMoney(overviewData.revenue || 0)}</strong>
 <span className="stat-subtext">Historical business total</span>
 </div>
 <div className="stat-card">
 <h3>Orders Analyzed</h3>
 <strong>{overviewData.orders || 0}</strong>
 <span className="stat-subtext">ML training dataset</span>
 </div>
 <div className="stat-card">
 <h3>Positive Sentiment</h3>
 <strong>{overviewData.sentiment?.positive_percentage || 0}%</strong>
 <span className="stat-subtext">NLP customer reviews</span>
 </div>
 <div className="stat-card">
 <h3>7-Day Projected Revenue</h3>
 <strong>{formatMoney(overviewData.revenue_forecast?.predicted_total_revenue || 0)}</strong>
 <span className="stat-subtext">Linear regression forecast</span>
 </div>
 <div className="stat-card">
 <h3>Low Stock Alerts</h3>
 <strong className={overviewData.low_stock_count > 0 ? "warning-text" : ""}>
 {overviewData.low_stock_count || 0}
 </strong>
 <span className="stat-subtext">Items needing reorder</span>
 </div>
 </div>

 {/* AI Executive Insights List */}
 <div className="ai-insights-container">
 <h2>Strategic Operational Insights</h2>
 <div className="insights-grid">
 {overviewData.insights?.map((ins, idx) => (
 <div className="ai-insight-card"key={idx}>
 <div className="ai-icon"></div>
 <div>
 <h3>Strategic Finding #{idx + 1}</h3>
 <p>{ins}</p>
 </div>
 </div>
 ))}
 </div>
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 1: FOOD RECOMMENDATION ENGINE
 ========================================================= */}
 {activeModule === "recommender" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <div className="module-title-row">
 <div>
 <h2>AI Food Recommendation Engine</h2>
 <p>
 Calculates personalized dish recommendations based on past order history, category affinity, customer ratings, and collaborative popularity.
 </p>
 </div>
 <div className="customer-test-picker">
 <label>Evaluate for Customer:</label>
 <select
 value={selectedCustomer}
 onChange={(e) =>handleCustomerChange(e.target.value)}
 >
 {customersList.map((c) => (
 <option key={c} value={c}>
 {c}
 </option>
 ))}
 </select>
 </div>
 </div>

 {customerRecs && (
 <div className="rec-analysis-box">
 <div className="analysis-meta-chips">
 <span className="meta-chip">Strategy: <strong>{customerRecs.strategy}</strong></span>
 <span className="meta-chip">Orders Analyzed: <strong>{customerRecs.orders_analyzed}</strong></span>
 <span className="meta-chip">Favorite Taste: <strong>{customerRecs.favourite_dish}</strong></span>
 </div>

 <h3>Top Recommended Dishes for {selectedCustomer}</h3>
 <div className="rec-cards-grid">
 {customerRecs.recommendations?.map((r, i) => (
 <div className="rec-result-card"key={i}>
 <div className="rec-rank-badge">#{i + 1}</div>
 <h4>{r.menu_item}</h4>
 <span className="rec-category">{r.category}</span>
 <p className="rec-reason-text"> {r.reason}</p>
 <div className="rec-footer-row">
 {/* A cosine similarity is a ranking value, not a
 calibrated probability. Labelling it
 "Confidence"and defaulting a missing score to
 0.8 would show an 80% confidence the model
 never computed, so the raw score is shown
 instead. */}
 <span
 className="rec-score-pill"
 title="Similarity score (0-1). Not a confidence probability."
 >
 Score: {(r.score ?? 0).toFixed(3)}
 </span>
 <strong className="rec-price-val">{formatMoney(r.price)}</strong>
 </div>
 </div>
 ))}
 </div>
 </div>
 )}

 {/* Trending / Popular Dishes */}
 <div className="popular-dishes-section">
 <h3>Top Trending Dishes Across All Customers</h3>
 <div className="popular-dishes-table">
 <table>
 <thead>
 <tr>
 <th>Dish Name</th>
 <th>Total Quantity Ordered</th>
 <th>Popularity Ranking</th>
 </tr>
 </thead>
 <tbody>
 {popularDishes.map((p, idx) => (
 <tr key={idx}>
 <td><strong>{p.menu_item}</strong></td>
 <td>{p.total_quantity} orders</td>
 <td><span className="rank-tag">Top #{idx + 1}</span></td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 </div>
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 2: SENTIMENT ANALYSIS
 ========================================================= */}
 {activeModule === "sentiment" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <h2>Customer Sentiment & Review NLP Classifier</h2>
 <p>
 Natural Language Processing model categorizing reviews into Positive, Neutral, or Negative, calculating polarity score, and extracting key feedback patterns.
 </p>

 {sentimentSummary && (
 <div className="sentiment-kpi-row">
 <div className="sentiment-stat positive">
 <h3>Positive Reviews</h3>
 <strong>{sentimentSummary.positive}</strong>
 <span>{sentimentSummary.positive_percentage}% of total</span>
 </div>
 <div className="sentiment-stat neutral">
 <h3>Neutral Reviews</h3>
 <strong>{sentimentSummary.neutral}</strong>
 <span>{Math.round((sentimentSummary.neutral / (sentimentSummary.total_reviews || 1)) * 100)}% of total</span>
 </div>
 <div className="sentiment-stat negative">
 <h3>Negative Reviews</h3>
 <strong>{sentimentSummary.negative}</strong>
 <span>{Math.round((sentimentSummary.negative / (sentimentSummary.total_reviews || 1)) * 100)}% of total</span>
 </div>
 <div className="sentiment-stat rating">
 <h3>Avg Star Rating</h3>
 <strong>{sentimentSummary.average_rating} / 5.0</strong>
 <span>{sentimentSummary.overall}</span>
 </div>
 </div>
 )}

 {/* Interactive NLP Sandbox */}
 <div className="nlp-sandbox-card">
 <h3>Interactive NLP Sentiment Classifier Sandbox</h3>
 <p>Type any customer review sentence to test the NLP classification in real time:</p>
 <div className="sandbox-input-row">
 <input
 type="text"
 value={sandboxText}
 onChange={(e) =>setSandboxText(e.target.value)}
 placeholder="Type a review sentence..."
 />
 <button
 className="primary-btn"
 onClick={handleAnalyzeSandbox}
 disabled={analyzingSandbox}
 >
 {analyzingSandbox ? "Analyzing..." : "Classify with NLP"}
 </button>
 </div>

 {sandboxResult && (
 <div className={`sandbox-result-box ${sandboxResult.sentiment.toLowerCase()}`}>
 <div className="sandbox-res-header">
 <span>NLP Classification:</span>
 <strong>
 {sandboxResult.sentiment === "Positive"
 ? "Positive "
 : sandboxResult.sentiment === "Negative"
 ? "Negative "
 : "Neutral "}
 </strong>
 </div>
 <div className="sandbox-res-details">
 <span>Polarity Score: <strong>{Number(sandboxResult.score).toFixed(2)}</strong></span>
 {/* This is the model's own predict_proba confidence,
 not a number derived from the polarity score. The
 API returns it directly. */}
 <span>
 Confidence:{" "}
 <strong>
 {sandboxResult.confidence !== undefined
 ? `${(Number(sandboxResult.confidence) * 100).toFixed(1)}%`
 : "not reported"}
 </strong>
 </span>
 </div>
 </div>
 )}
 </div>

 {/* Top Complaints & Improvement Points */}
 {sentimentSummary?.top_complaints && sentimentSummary.top_complaints.length > 0 && (
 <div className="complaints-section">
 <h3>Actionable Operational Alerts (Identified by NLP)</h3>
 <div className="complaints-list">
 {sentimentSummary.top_complaints.map((c, i) => (
 <div className="complaint-card"key={i}>
 <div className="complaint-header">
 <strong>{c.menu_item}</strong>
 <span className="complaint-stars">{"★".repeat(c.rating || 2)}</span>
 </div>
 <p>"{c.comment}"</p>
 </div>
 ))}
 </div>
 </div>
 )}
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 3: DEMAND PREDICTION
 ========================================================= */}
 {activeModule === "demand" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <h2>Food Demand Prediction (7-Day Forecast)</h2>
 <p>
 Linear regression time-series forecasting expected daily demand for each menu item to optimize kitchen prep and minimize ingredient shortages.
 </p>

 {demandData && (
 <div className="demand-table-wrap">
 <table className="ai-data-table">
 <thead>
 <tr>
 <th>Menu Item</th>
 <th>Model Used</th>
 <th>Historical Daily Avg</th>
 <th>Trend Direction</th>
 <th>Predicted 7-Day Total</th>
 <th>Recommended Action</th>
 </tr>
 </thead>
 <tbody>
 {demandData.forecast?.map((item, idx) => (
 <tr key={idx}>
 <td><strong>{item.menu_item}</strong></td>
 <td><span className="code-pill">{item.model}</span></td>
 <td>{Number(item.historical_daily_average).toFixed(1)} units/day</td>
 <td>
 <span className={`trend-badge ${item.trend}`}>
 {item.trend === "rising" ? "Rising Demand" : item.trend === "falling" ? "Decreasing" : "Stable"}
 </span>
 </td>
 <td>
 <strong className="projected-qty">
 {Math.round(item.predicted_total)} portions
 </strong>
 </td>
 <td>
 {item.trend === "rising"
 ? "Increase prep batch by +15%"
 : item.trend === "falling"
 ? "Reduce prep batch to prevent waste"
 : "Standard batch prep"}
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 )}
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 4: REVENUE PREDICTION
 ========================================================= */}
 {activeModule === "revenue" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <h2>Revenue Prediction & Financial Forecasting</h2>
 <p>
 Machine Learning model fitted over 60 days of business transactions projecting expected future revenue with daily trajectory.
 </p>

 {revenueData && (
 <>
 <div className="revenue-kpi-summary">
 <div className="rev-kpi-box">
 <span>Expected 7-Day Revenue</span>
 <strong>{formatMoney(revenueData.predicted_total_revenue || 0)}</strong>
 </div>
 <div className="rev-kpi-box">
 <span>Predicted Daily Average</span>
 <strong>{formatMoney(revenueData.predicted_daily_average || 0)}</strong>
 </div>
 <div className="rev-kpi-box">
 <span>Model Outlook</span>
 <strong className="outlook-tag">{revenueData.outlook}</strong>
 </div>
 </div>

 <h3>Daily Projected Revenue Trajectory</h3>
 <div className="forecast-days-grid">
 {revenueData.forecast?.map((day, i) => (
 <div className="day-forecast-card"key={i}>
 <span className="forecast-date">{day.date}</span>
 <strong className="forecast-amount">{formatMoney(day.predicted_revenue)}</strong>
 <span className="forecast-lbl">Projected</span>
 </div>
 ))}
 </div>
 </>
 )}
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 5: WASTE ANALYSIS
 ========================================================= */}
 {activeModule === "waste" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <h2>Food Waste Pattern Analysis & Reduction Engine</h2>
 <p>
 Correlates inventory consumption, customer orders, and kitchen waste records using Random Forest Regression to isolate wastage hotspots and provide actionable mitigation.
 </p>

 {wasteData && (
 <>
 <div className="waste-stats-row">
 <div className="waste-stat-card">
 <span>Total Waste Logged</span>
 <strong>{Number(wasteData.total_waste_quantity).toFixed(1)} kg</strong>
 </div>
 <div className="waste-stat-card">
 <span>Total Financial Loss</span>
 <strong>{formatMoney(wasteData.total_waste_cost)}</strong>
 </div>
 <div className="waste-stat-card">
 <span>Predicted Next Week Waste</span>
 <strong>{Number(wasteData.predicted_next_week_quantity).toFixed(1)} kg</strong>
 </div>
 </div>

 {/* AI Waste Reduction Recommendations */}
 <div className="waste-rec-box">
 <h3>AI Waste Reduction Recommendations</h3>
 <ul>
 {wasteData.recommendations?.map((rec, i) => (
 <li key={i}>{rec}</li>
 ))}
 </ul>
 </div>

 {/* Waste Patterns by Item */}
 <div className="waste-breakdown-row">
 <div className="waste-breakdown-card">
 <h3>Wastage by Ingredient</h3>
 <div className="waste-bars-list">
 {wasteData.patterns?.by_item?.map((item, i) => (
 <div className="waste-bar-item"key={i}>
 <div className="waste-bar-header">
 <span>{item.item_name}</span>
 <strong>{item.quantity} kg ({formatMoney(item.cost)})</strong>
 </div>
 <div className="bar-track">
 <div
 className="bar-fill"
 style={{ width: `${Math.min(100, (item.quantity / 35) * 100)}%` }}
 />
 </div>
 </div>
 ))}
 </div>
 </div>

 {/* Waste by Reason */}
 <div className="waste-breakdown-card">
 <h3>Wastage by Operational Cause</h3>
 <div className="waste-bars-list">
 {wasteData.patterns?.by_reason?.map((reason, i) => (
 <div className="waste-bar-item"key={i}>
 <div className="waste-bar-header">
 <span>{reason.reason}</span>
 <strong>{reason.quantity} kg</strong>
 </div>
 <div className="bar-track">
 <div
 className="bar-fill reason"
 style={{ width: `${Math.min(100, (reason.quantity / 30) * 100)}%` }}
 />
 </div>
 </div>
 ))}
 </div>
 </div>
 </div>
 </>
 )}
 </div>
 </div>
 )}

 {/* =========================================================
 MODULE 6: DYNAMIC PRICING
 ========================================================= */}
 {activeModule === "pricing" && (
 <div className="ai-tab-content">
 <div className="ai-module-card">
 <h2>AI-Driven Dynamic Pricing Engine</h2>
 <p>
 Combines recent sales velocity, demand elasticity, stock availability, and weekday/weekend patterns to suggest revenue-maximizing prices.
 </p>

 {priceSuccessMsg && (
 <div className="success-banner">{priceSuccessMsg}</div>
 )}

 {pricingData && (
 <div className="pricing-table-wrap">
 <table className="ai-data-table">
 <thead>
 <tr>
 <th>Dish Name</th>
 <th>Category</th>
 <th>Current Price</th>
 <th>AI Suggested Price</th>
 <th>Price Adjustment</th>
 <th>Algorithmic Rationale</th>
 <th>Action</th>
 </tr>
 </thead>
 <tbody>
 {pricingData.suggestions?.map((item, idx) => {
 const change = item.change_percentage || 0;
 return (
 <tr key={idx}>
 <td><strong>{item.menu_item}</strong></td>
 <td>{item.category}</td>
 <td>{formatMoney(item.current_price)}</td>
 <td>
 <strong className="suggested-price-val">
 {formatMoney(item.suggested_price)}
 </strong>
 </td>
 <td>
 <span
 className={`price-change-pill ${
 change > 0 ? "increase" : change < 0 ? "discount" : "neutral"
 }`}
 >
 {change > 0 ? `+${change}%` : `${change}%`}
 </span>
 </td>
 <td className="rationale-cell">
 {item.reason}
 </td>
 <td>
 <button
 className="apply-price-btn"
 disabled={applyingPriceItem === item.menu_item || change === 0}
 onClick={() =>handleApplyPrice(item)}
 >
 {applyingPriceItem === item.menu_item
 ? "Updating..."
 : change === 0
 ? "Optimal"
 : "Apply to Menu"}
 </button>
 </td>
 </tr>
 );
 })}
 </tbody>
 </table>
 </div>
 )}
 </div>
 </div>
 )}
 </div>
 );
}

export default AIInsights;