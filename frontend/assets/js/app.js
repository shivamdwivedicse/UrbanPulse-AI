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

        await loadPrediction();

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