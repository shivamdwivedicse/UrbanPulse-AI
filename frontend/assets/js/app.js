// ========================================
// UrbanPulse AI - Frontend Application
// ========================================

const API_BASE_URL = "http://127.0.0.1:8000";
const BIN_ID = "BIN-PROTOTYPE-01";

// DOM Elements
const dateElement = document.getElementById("todayDate");
const refreshButton = document.getElementById("refreshBtn");
const predictionBtn = document.getElementById("generatePredictionBtn");
const toast = document.getElementById("toast");
const menuToggle = document.getElementById("menuToggle");
const sidebar = document.getElementById("sidebar");

// ========================================
// DATE
// ========================================

if (dateElement) {
    dateElement.textContent = new Intl.DateTimeFormat("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    }).format(new Date());
}

// ========================================
// TOAST NOTIFICATION
// ========================================

function showToast(message) {
    if (!toast) return;

    toast.textContent = message;
    toast.classList.add("show");

    setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

// ========================================
// UPDATE HTML ELEMENT
// ========================================

function updateText(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.textContent = value;
    }
}

// ========================================
// API REQUEST
// ========================================

async function fetchAPI(endpoint) {

    const response = await fetch(
        `${API_BASE_URL}${endpoint}`
    );

    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }

    return await response.json();
}

// ========================================
// HEALTH CHECK
// ========================================

async function loadHealth() {

    const health = await fetchAPI("/health");

    const modelStatus = health.model_status;

    const isHealthy =
        health.status === "healthy" &&
        modelStatus.loaded;

    updateText(
        "apiStatus",
        isHealthy ? "Connected" : "Unavailable"
    );

    updateText(
        "predictionStatus",
        modelStatus.loaded
            ? "ML Model Ready"
            : "Model Unavailable"
    );

    const apiDot = document.getElementById("apiDot");

    if (apiDot) {
        apiDot.style.background =
            isHealthy ? "#28c995" : "#ef5350";
    }

    updateText(
        "systemStatus",
        isHealthy ? "SYSTEM ONLINE" : "SYSTEM OFFLINE"
    );

    return health;
}

// ========================================
// LOAD BIN DATA
// ========================================

async function loadBins() {

    const response = await fetchAPI("/api/v1/bins");

    updateText(
        "totalBins",
        String(response.total_bins).padStart(2, "0")
    );

    updateText(
        "navBinCount",
        String(response.total_bins).padStart(2, "0")
    );

    if (!response.bins || response.bins.length === 0) {
        throw new Error("No bins available.");
    }

    const bin = response.bins.find(
        item => item.bin_id === BIN_ID
    );

    if (!bin) {
        throw new Error("Prototype bin not found.");
    }

    updateText(
        "totalRecords",
        bin.total_historical_records.toLocaleString("en-IN")
    );

    updateText("binName", bin.bin_id);

    const fillLevel = Number(
        bin.latest_recorded_fill_level
    );

    updateText("latestFill", fillLevel.toFixed(1));

    const percentage = Math.max(
        0,
        Math.min(100, (fillLevel / 10) * 100)
    );

    const progress = document.getElementById("fillProgress");

    if (progress) {
        progress.style.width = `${percentage}%`;
    }

    const observationDate = new Date(
        bin.latest_reading_date.replace(" ", "T")
    );

    updateText(
        "lastObservation",
        observationDate.toLocaleDateString("en-IN", {
            day: "2-digit",
            month: "short",
            year: "numeric"
        })
    );

    return bin;
}

// ========================================
// HISTORICAL FILL-LEVEL CHART
// ========================================

const CHART_WIDTH = 760;
const CHART_HEIGHT = 220;
const FILL_SCALE_MAX = 10;

function parseObservationTime(value) {
    return new Date(String(value).replace(" ", "T")).getTime();
}

function formatAxisDate(value) {
    const date = new Date(String(value).replace(" ", "T"));
    return date.toLocaleDateString("en-IN", {
        month: "short",
        year: "numeric"
    });
}

function buildChartPaths(observations) {
    if (!observations || observations.length === 0) {
        return { line: "", area: "" };
    }

    const times = observations.map(item => parseObservationTime(item.datetime));
    const start = times[0];
    const span = Math.max(times[times.length - 1] - start, 1);

    const points = observations.map((item, index) => {
        const x = ((times[index] - start) / span) * CHART_WIDTH;
        const fill = Math.max(0, Math.min(FILL_SCALE_MAX, Number(item.fill_level)));
        const y = CHART_HEIGHT - (fill / FILL_SCALE_MAX) * CHART_HEIGHT;
        return `${x.toFixed(2)} ${y.toFixed(2)}`;
    });

    const line = `M ${points.join(" L ")}`;
    const area = `${line} L ${CHART_WIDTH} ${CHART_HEIGHT} L 0 ${CHART_HEIGHT} Z`;
    return { line, area };
}

function renderHistoryAxis(history) {
    const axis = document.getElementById("historyXAxis");
    if (!axis) return;

    const start = parseObservationTime(history.start_date);
    const end = parseObservationTime(history.end_date);
    const span = Math.max(end - start, 1);
    const ticks = 5;

    axis.innerHTML = "";
    for (let i = 0; i < ticks; i += 1) {
        const stamp = new Date(start + (span * i) / (ticks - 1));
        const label = document.createElement("span");
        label.textContent = stamp.toLocaleDateString("en-IN", {
            month: "short",
            year: "numeric"
        });
        axis.appendChild(label);
    }
}

function renderHistoryChart(history) {
    const areaPath = document.getElementById("historyArea");
    const linePath = document.getElementById("historyLine");
    const paths = buildChartPaths(history.observations);

    if (areaPath) areaPath.setAttribute("d", paths.area);
    if (linePath) linePath.setAttribute("d", paths.line);

    renderHistoryAxis(history);

    updateText(
        "historyCount",
        Number(history.total_observations).toLocaleString("en-IN")
    );
    updateText("historyMin", Number(history.min_fill_level).toFixed(1));
    updateText("historyMax", Number(history.max_fill_level).toFixed(1));
    updateText("historyAvg", Number(history.average_fill_level).toFixed(2));

    const disclaimer = document.getElementById("historyDisclaimer");
    if (disclaimer) {
        disclaimer.classList.remove("error");
        disclaimer.textContent = (
            "Historical research dataset (2018–2020). " +
            `${formatAxisDate(history.start_date)} to ${formatAxisDate(history.end_date)}. ` +
            "These are cleaned observed readings, not live IoT telemetry."
        );
    }
}

function clearHistoryChart(message) {
    const areaPath = document.getElementById("historyArea");
    const linePath = document.getElementById("historyLine");
    if (areaPath) areaPath.setAttribute("d", "");
    if (linePath) linePath.setAttribute("d", "");

    updateText("historyCount", "--");
    updateText("historyMin", "--");
    updateText("historyMax", "--");
    updateText("historyAvg", "--");

    const disclaimer = document.getElementById("historyDisclaimer");
    if (disclaimer) {
        disclaimer.classList.add("error");
        disclaimer.textContent = message;
    }
}

async function loadHistory() {
    const history = await fetchAPI(`/api/v1/bins/${BIN_ID}/history`);

    if (!history.observations || history.observations.length === 0) {
        throw new Error("No historical observations returned.");
    }

    renderHistoryChart(history);
    return history;
}

// ========================================
// GENERATE ML PREDICTION
// ========================================

async function loadPrediction() {

    updateText("predictionStatus", "Generating...");
    updateText("predictedFill", "--");

    const prediction = await fetchAPI(
        `/api/v1/bins/${BIN_ID}/prediction`
    );

    const predictedValue = Number(
        prediction.bounded_prediction
    );

    updateText(
        "predictedFill",
        predictedValue.toFixed(3)
    );

    updateText(
        "predictionDate",
        `Forecast date: ${prediction.prediction_timestamp}`
    );

    updateText(
        "predictionStatus",
        prediction.was_clipped
            ? `Prediction bounded (${prediction.clip_direction})`
            : "Prediction successful"
    );

    return prediction;
}

// ========================================
// DASHBOARD INITIALIZATION
// ========================================

async function loadDashboard() {

    try {

        updateText("apiStatus", "Connecting...");
        updateText("predictionStatus", "Loading...");

        await loadHealth();

        await loadBins();

        try {
            await loadPrediction();
        } catch (predictionError) {
            console.error("Prediction failed:", predictionError);
            updateText("predictionStatus", "Prediction failed");
            updateText("predictedFill", "--");
        }

        try {
            await loadHistory();
        } catch (historyError) {
            console.error("History chart failed:", historyError);
            clearHistoryChart(
                "Unable to load historical observations. Check the backend history endpoint."
            );
        }

        console.log(
            "UrbanPulse AI dashboard loaded successfully."
        );

        showToast("Dashboard connected successfully.");

    } catch (error) {

        console.error(
            "Dashboard loading failed:",
            error
        );

        updateText("apiStatus", "Offline");
        updateText("predictionStatus", "API unavailable");
        updateText("predictedFill", "--");

        showToast(
            "Unable to load data. Check backend server."
        );
    }
}

// ========================================
// MANUAL PREDICTION BUTTON
// ========================================

predictionBtn?.addEventListener("click", async () => {

    predictionBtn.disabled = true;

    predictionBtn.textContent = "⏳ Generating...";

    try {

        await loadPrediction();

        showToast(
            "ML prediction generated successfully!"
        );

    } catch (error) {

        console.error(
            "Prediction failed:",
            error
        );

        updateText(
            "predictionStatus",
            "Prediction failed"
        );

        showToast(
            "Prediction failed. Check backend."
        );

    } finally {

        predictionBtn.disabled = false;

        predictionBtn.textContent =
            "⚡ Generate Prediction";
    }
});

// ========================================
// REFRESH DASHBOARD
// ========================================

refreshButton?.addEventListener("click", async () => {

    refreshButton.disabled = true;

    refreshButton.innerHTML =
        "<span>↻</span> Refreshing...";

    await loadDashboard();

    refreshButton.disabled = false;

    refreshButton.innerHTML =
        "<span>↻</span> Refresh data";
});

// ========================================
// SIDEBAR MENU
// ========================================

menuToggle?.addEventListener("click", () => {

    sidebar?.classList.toggle("open");

});

// ========================================
// NAVIGATION
// ========================================

document.querySelectorAll(".nav-item").forEach(item => {

    item.addEventListener("click", () => {

        document.querySelectorAll(".nav-item").forEach(nav => {
            nav.classList.remove("active");
        });

        item.classList.add("active");

        if (window.innerWidth <= 760) {
            sidebar?.classList.remove("open");
        }

    });

});

// ========================================
// VIEW BIN BUTTON
// ========================================

document.getElementById("viewBinBtn")?.addEventListener(
    "click",
    () => {
        showToast(
            "Prototype: BIN-PROTOTYPE-01 | Historical data source"
        );
    }
);

// ========================================
// START APPLICATION
// ========================================

document.addEventListener(
    "DOMContentLoaded",
    loadDashboard
);