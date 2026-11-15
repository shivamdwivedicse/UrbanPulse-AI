// ========================================
// UrbanPulse AI - Frontend Application
// ========================================

const localHostname = window.location?.hostname;
const API_BASE_URL = window.URBANPULSE_API_BASE_URL || (
    localHostname === "localhost" || localHostname === "127.0.0.1"
        ? `${window.location.protocol}//${localHostname}:8000`
        : window.location?.origin || "http://127.0.0.1:8000"
);
const BIN_ID = "BIN-PROTOTYPE-01";

// DOM Elements
const dateElement = document.getElementById("todayDate");
const refreshButton = document.getElementById("refreshBtn");
const predictionBtn = document.getElementById("generatePredictionBtn");
const toast = document.getElementById("toast");
const menuToggle = document.getElementById("menuToggle");
const sidebar = document.getElementById("sidebar");
const wasteAnalysisForm = document.getElementById("wasteAnalysisForm");
const wasteImageInput = document.getElementById("wasteImage");
const analyzeWasteButton = document.getElementById("analyzeWasteBtn");

const MAX_WASTE_IMAGE_BYTES = 8 * 1024 * 1024;
const WASTE_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const WASTE_ANALYSIS_BUSY_MESSAGE =
    "AI image analysis is temporarily busy. Please try again in a few minutes.";
let wastePreviewUrl = null;
let lastHistoryData = null;
let complaintRecords = [];
let currentComplaintRows = [];
let cityMap = null;
let cityMapLayers = [];
let lastOptimizedRoute = null;
let availableBins = [];

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

    const modelStatus = health.model_status || {};
    const isHealthy = health.status === "healthy";

    updateText(
        "apiStatus",
        isHealthy ? "Connected" : "Unavailable"
    );
    updateText(
        "settingsApiStatus",
        isHealthy ? "Connected" : "Unavailable"
    );
    updateText(
        "settingsApiDetails",
        `${health.app_name || "UrbanPulse API"} · ${health.version || "Version unavailable"}`
    );

    updateText(
        "predictionStatus",
        modelStatus.loaded ? "ML model ready" : "Model unavailable"
    );

    ["apiDot", "settingsApiDot"].forEach(id => {
        const apiDot = document.getElementById(id);
        if (apiDot) {
            apiDot.classList.toggle("is-connected", isHealthy);
            apiDot.classList.toggle("is-disconnected", !isHealthy);
        }
    });
    document.getElementById("complaintSearch")?.addEventListener("input", () => {
        renderComplaintRows(currentComplaintRows);
    });
    document.getElementById("complaintPriorityFilter")?.addEventListener("change", () => loadComplaints());
    updateText("systemStatus", isHealthy ? "API CONNECTED" : "API OFFLINE");

    return health;
}

// ========================================
// LOAD BIN DATA
// ========================================

async function loadBins() {

    const response = await fetchAPI("/api/v1/bins");
    availableBins = Array.isArray(response.bins) ? response.bins : [];

    updateText(
        "totalBins",
        String(response.total_bins).padStart(2, "0")
    );

    updateText(
        "navBinCount",
        String(response.total_bins).padStart(2, "0")
    );

    if (availableBins.length === 0) {
        throw new Error("No bins available.");
    }

    const bin = availableBins.find(
        item => item.bin_id === BIN_ID
    );

    if (!bin) {
        throw new Error("Prototype bin not found.");
    }

    updateText(
        "totalRecords",
        bin.total_historical_records.toLocaleString("en-IN")
    );
    updateText(
        "predictionDatasetCount",
        Number(bin.total_historical_records).toLocaleString("en-IN")
    );
    updateText(
        "overviewLatestFill",
        Number(bin.latest_recorded_fill_level).toFixed(1)
    );
    updateText(
        "binRecordCount",
        Number(bin.total_historical_records).toLocaleString("en-IN")
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
    updateText(
        "overviewLatestDate",
        observationDate.toLocaleDateString("en-IN", {
            day: "2-digit",
            month: "short",
            year: "numeric"
        })
    );

    renderCityMapLayers();
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
    lastHistoryData = history;
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

    renderRecentHistoryRows(history.observations);
}

function renderRecentHistoryRows(observations) {
    const body = document.getElementById("recentHistoryRows");
    if (!body) return;
    body.replaceChildren();
    observations.slice(-8).reverse().forEach(observation => {
        const row = document.createElement("tr");
        const dateCell = document.createElement("td");
        dateCell.textContent = formatPredictionDate(observation.datetime);
        const fillCell = document.createElement("td");
        fillCell.textContent = `${Number(observation.fill_level).toFixed(2)} / 10`;
        const sourceCell = document.createElement("td");
        sourceCell.textContent = "Cleaned historical CSV";
        row.appendChild(dateCell);
        row.appendChild(fillCell);
        row.appendChild(sourceCell);
        body.appendChild(row);
    });
}

function clearHistoryChart(message) {
    lastHistoryData = null;
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
    const body = document.getElementById("recentHistoryRows");
    if (body) {
        body.replaceChildren();
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 3;
        cell.textContent = message;
        row.appendChild(cell);
        body.appendChild(row);
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

function formatPredictionDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:\s|T)/.exec(String(value ?? ""));
    if (!match) return String(value || "--");

    const date = new Date(Date.UTC(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3])
    ));
    return new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: "UTC"
    }).format(date);
}

function clearPredictionDetails() {
    updateText("predictedFill", "--");
    updateText("predictionBinId", "--");
    updateText("predictionDate", "--");
    updateText("predictionBaseDate", "--");
    updateText("predictionModel", "--");
    updateText("binPredictionValue", "—");
    updateText("binPredictionDate", "—");
    updateText("binPredictionBaseDate", "—");
    updateText("binPredictionModel", "—");
}

function setPredictionState(message, state) {
    ["predictionStatus", "binPredictionStatus"].forEach(id => {
        const status = document.getElementById(id);
        if (!status) return;
        status.textContent = message;
        status.classList.remove("loading", "error");
        if (state) status.classList.add(state);
    });
}

async function loadPrediction() {
    clearPredictionDetails();
    setPredictionState("Loading historical estimate...", "loading");

    const prediction = await fetchAPI(
        `/api/v1/bins/${BIN_ID}/prediction`
    );

    const predictedValue = Number(
        prediction.bounded_prediction
    );
    if (!Number.isFinite(predictedValue) || predictedValue < 0 || predictedValue > 10) {
        throw new Error("Prediction response is outside the expected 0–10 scale.");
    }

    updateText(
        "predictedFill",
        String(prediction.bounded_prediction)
    );

    updateText("predictionBinId", prediction.bin_id);
    updateText("predictionDate", formatPredictionDate(prediction.prediction_timestamp));
    updateText("predictionBaseDate", formatPredictionDate(prediction.historical_base_date));
    updateText("predictionModel", prediction.model_name);
    updateText("binPredictionValue", String(prediction.bounded_prediction));
    updateText("binPredictionDate", formatPredictionDate(prediction.prediction_timestamp));
    updateText("binPredictionBaseDate", formatPredictionDate(prediction.historical_base_date));
    updateText("binPredictionModel", prediction.model_name);
    updateText(
        "binPredictionStatus",
        prediction.was_clipped
            ? `Bounded to the valid scale (${prediction.clip_direction})`
            : "Historical estimate generated"
    );

    setPredictionState(
        prediction.was_clipped
            ? `Prediction bounded (${prediction.clip_direction})`
            : "Historical estimate generated",
        ""
    );

    return prediction;
}

// ========================================
// GEMINI WASTE IMAGE ANALYSIS
// ========================================

function setWasteAnalysisError(message) {
    const errorElement = document.getElementById("wasteAnalysisError");
    const statusElement = document.getElementById("wasteAnalysisStatus");
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.hidden = !message;
    }
    if (statusElement) {
        statusElement.textContent = message ? "Analysis failed." : "Select an image to begin.";
        statusElement.classList.toggle("error", Boolean(message));
    }
}

function resetWasteAnalysisResult() {
    const result = document.getElementById("wasteAnalysisResult");
    if (result) result.hidden = true;
    const severity = document.getElementById("wasteSeverity");
    if (severity) {
        severity.textContent = "";
        severity.className = "waste-severity";
    }
    const uncertainty = document.getElementById("wasteUncertainty");
    if (uncertainty) uncertainty.hidden = true;
}

function displayWasteAnalysis(analysis) {
    const valueOrUnknown = value => value || "Unable to assess";
    updateText("wasteCategory", valueOrUnknown(analysis.category));
    updateText("wasteAccumulation", valueOrUnknown(analysis.accumulation_assessment));
    updateText("wasteOverflow", valueOrUnknown(analysis.overflow_assessment));
    updateText("wasteExplanation", analysis.explanation);
    updateText("wasteRecommendedAction", analysis.recommended_action);

    const severity = document.getElementById("wasteSeverity");
    if (severity) {
        severity.textContent = analysis.severity || "SEVERITY UNAVAILABLE";
        severity.className = `waste-severity ${(analysis.severity || "").toLowerCase()}`;
    }

    const uncertainty = document.getElementById("wasteUncertainty");
    if (uncertainty) {
        uncertainty.hidden = !analysis.is_uncertain;
        uncertainty.textContent = analysis.is_uncertain
            ? `Uncertain: ${analysis.uncertainty_reason || "Some details cannot be determined from this image."}`
            : "";
    }

    const result = document.getElementById("wasteAnalysisResult");
    if (result) result.hidden = false;
}

// ========================================
// VERIFIED CITY MAP LAYERS
// ========================================

function initializeCityMap() {
    const mapElement = document.getElementById("cityMap");
    if (!mapElement) return;
    if (typeof L === "undefined") {
        updateText("cityMapStatus", "Map library unavailable.");
        return;
    }

    cityMap = L.map(mapElement).setView([20, 0], 2);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(cityMap);
    renderCityMapLayers();
}

function renderCityMapLayers() {
    const emptyState = document.getElementById("cityMapEmpty");
    if (!cityMap || typeof L === "undefined") {
        if (emptyState && typeof L === "undefined") {
            emptyState.textContent = "The map library is unavailable. Geolocated complaint records remain available in the register.";
            emptyState.hidden = false;
        }
        return;
    }

    cityMapLayers.forEach(layer => cityMap.removeLayer(layer));
    cityMapLayers = [];
    const points = [];
    const showBins = document.getElementById("mapShowBins")?.checked !== false;
    const showComplaints = document.getElementById("mapShowComplaints")?.checked !== false;
    const showRoute = document.getElementById("mapShowRoute")?.checked === true;
    let visibleBinCount = 0;
    let visibleComplaintCount = 0;
    let routeVisible = false;

    if (showBins) {
        availableBins.filter(bin =>
            bin.latitude !== null
            && bin.longitude !== null
            && bin.latitude !== undefined
            && bin.longitude !== undefined
            && Number.isFinite(Number(bin.latitude))
            && Number.isFinite(Number(bin.longitude))
        ).forEach(bin => {
            const point = [Number(bin.latitude), Number(bin.longitude)];
            const marker = L.marker(point).bindPopup(
                document.createTextNode(`${bin.bin_id} · verified coordinates from bin inventory`)
            ).addTo(cityMap);
            cityMapLayers.push(marker);
            points.push(point);
            visibleBinCount += 1;
        });
    }

    if (showComplaints) {
        complaintRecords.filter(complaint =>
            complaint.latitude !== null
            && complaint.longitude !== null
            && complaint.latitude !== undefined
            && complaint.longitude !== undefined
            && Number.isFinite(Number(complaint.latitude))
            && Number.isFinite(Number(complaint.longitude))
        ).forEach(complaint => {
            const point = [Number(complaint.latitude), Number(complaint.longitude)];
            const marker = L.marker(point).bindPopup(
                document.createTextNode(
                    `${complaint.complaint_id} · ${complaint.category} · ${complaint.status}`
                )
            ).addTo(cityMap);
            cityMapLayers.push(marker);
            points.push(point);
            visibleComplaintCount += 1;
        });
    }

    if (
        showRoute
        && lastOptimizedRoute
        && Array.isArray(lastOptimizedRoute.stops)
        && lastOptimizedRoute.stops.length
    ) {
        const depot = lastOptimizedRoute.depot;
        const routePoints = [
            [depot.latitude, depot.longitude],
            ...lastOptimizedRoute.stops.map(stop => [stop.latitude, stop.longitude]),
            [depot.latitude, depot.longitude]
        ];
        const line = L.polyline(routePoints, {
            color: getComputedStyle(document.documentElement)
                .getPropertyValue("--color-emerald")
                .trim(),
            weight: 4,
            opacity: 0.85,
            dashArray: "7 7"
        }).addTo(cityMap);
        cityMapLayers.push(line);
        routeVisible = true;
        points.push(...routePoints);
    }

    if (points.length) {
        cityMap.fitBounds(L.latLngBounds(points), { padding: [24, 24], maxZoom: 15 });
    } else {
        cityMap.setView([20, 0], 2);
    }

    if (emptyState) emptyState.hidden = visibleBinCount > 0 || visibleComplaintCount > 0;
    updateText(
        "cityMapStatus",
        `${visibleComplaintCount} geolocated complaint${visibleComplaintCount === 1 ? "" : "s"} · `
        + `${visibleBinCount} verified bin location${visibleBinCount === 1 ? "" : "s"} · `
        + (routeVisible ? "illustrative route shown" : "illustrative route hidden")
    );
}

// ========================================
// ILLUSTRATIVE OR-TOOLS ROUTE OPTIMIZATION
// ========================================

const illustrativeRouteStops = [
    { bin_id: "DEMO-BIN-01", latitude: 37.5675, longitude: 126.9790, fill_level: 8.2, priority: "HIGH" },
    { bin_id: "DEMO-BIN-02", latitude: 37.5700, longitude: 126.9810, fill_level: 4.5, priority: "LOW" },
    { bin_id: "DEMO-BIN-03", latitude: 37.5655, longitude: 126.9750, fill_level: 6.7, priority: "MEDIUM" },
    { bin_id: "DEMO-BIN-04", latitude: 37.5635, longitude: 126.9805, fill_level: 9.1, priority: "HIGH" }
];
let routeMap = null;
let routeMapLayers = [];
let routeStopSequence = illustrativeRouteStops.length + 1;

function createRouteField(labelText, fieldName, value, type = "text", options = {}) {
    const label = document.createElement("label");
    label.className = "route-stop-field";
    label.textContent = labelText;

    const input = document.createElement(type === "select" ? "select" : "input");
    input.dataset.field = fieldName;
    if (type !== "select") {
        input.type = type;
        input.value = String(value);
        input.step = options.step || "any";
        if (options.min !== undefined) input.min = String(options.min);
        if (options.max !== undefined) input.max = String(options.max);
        if (type === "text") input.maxLength = 80;
        input.required = true;
    } else {
        ["HIGH", "MEDIUM", "LOW"].forEach(priority => {
            const option = document.createElement("option");
            option.value = priority;
            option.textContent = priority;
            option.selected = priority === value;
            input.appendChild(option);
        });
    }

    label.appendChild(input);
    return label;
}

function addRouteStopRow(stop) {
    const stopList = document.getElementById("routeStopList");
    if (!stopList) return;

    const row = document.createElement("div");
    row.className = "route-stop-row";
    row.appendChild(createRouteField("Bin ID", "bin_id", stop.bin_id, "text"));
    row.appendChild(createRouteField("Latitude", "latitude", stop.latitude, "number", { min: -90, max: 90 }));
    row.appendChild(createRouteField("Longitude", "longitude", stop.longitude, "number", { min: -180, max: 180 }));
    row.appendChild(createRouteField("Fill (0–10)", "fill_level", stop.fill_level, "number", { min: 0, max: 10 }));
    row.appendChild(createRouteField("Priority", "priority", stop.priority, "select"));

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "route-remove-stop";
    removeButton.textContent = "Remove";
    removeButton.setAttribute("aria-label", `Remove ${stop.bin_id}`);
    removeButton.addEventListener("click", () => {
        row.remove();
        updateRouteStopCount();
    });
    row.appendChild(removeButton);
    stopList.appendChild(row);
    updateRouteStopCount();
}

function updateRouteStopCount() {
    const count = document.querySelectorAll("#routeStopList .route-stop-row").length;
    updateText("routeStopCount", `${count} illustrative stop${count === 1 ? "" : "s"} · edit coordinates, fill, or priority`);
}

function readRouteNumber(input, label, min, max) {
    if (!input.value.trim()) throw new Error(`${label} is required.`);
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < min || value > max) {
        throw new Error(`${label} must be between ${min} and ${max}.`);
    }
    return value;
}

function collectRouteRequest() {
    const depotName = document.getElementById("routeDepotName");
    const depotLatitude = document.getElementById("routeDepotLatitude");
    const depotLongitude = document.getElementById("routeDepotLongitude");
    if (!depotName?.value.trim()) throw new Error("Depot name is required.");

    const stops = Array.from(
        document.querySelectorAll("#routeStopList .route-stop-row")
    ).map(row => {
        const values = Object.fromEntries(
            Array.from(row.querySelectorAll("[data-field]"))
                .map(input => [input.dataset.field, input])
        );
        if (!values.bin_id.value.trim()) throw new Error("Every stop must have a bin ID.");
        return {
            bin_id: values.bin_id.value.trim(),
            latitude: readRouteNumber(values.latitude, "Stop latitude", -90, 90),
            longitude: readRouteNumber(values.longitude, "Stop longitude", -180, 180),
            fill_level: readRouteNumber(values.fill_level, "Fill level", 0, 10),
            priority: values.priority.value
        };
    });
    if (!stops.length) throw new Error("Add at least one collection stop.");

    return {
        depot: {
            name: depotName.value.trim(),
            latitude: readRouteNumber(depotLatitude, "Depot latitude", -90, 90),
            longitude: readRouteNumber(depotLongitude, "Depot longitude", -180, 180)
        },
        stops
    };
}

function initializeRouteMap() {
    const mapElement = document.getElementById("routeMap");
    if (!mapElement) return;
    if (typeof L === "undefined") {
        updateText("routeMapStatus", "Map library unavailable; route details remain available below.");
        return;
    }

    routeMap = L.map(mapElement).setView([37.5665, 126.9780], 14);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(routeMap);
    updateText("routeMapStatus", "Waiting for an optimized illustrative route.");
}

function renderOptimizedRoute(route) {
    lastOptimizedRoute = route;
    const result = document.getElementById("routeResults");
    if (result) result.hidden = false;
    const initialState = document.getElementById("routeInitialState");
    if (initialState) initialState.hidden = true;
    updateText("routeDistance", `${Number(route.total_estimated_distance_km).toFixed(2)} km`);
    updateText("routeResultStopCount", String(route.number_of_stops));
    updateText("routeOptimizationStatus", route.optimization_status.replaceAll("_", " "));
    updateText("routeMethodology", route.distance_methodology);

    const list = document.getElementById("routeOrderedStops");
    if (list) {
        list.replaceChildren();
        route.stops.forEach(stop => {
            const item = document.createElement("li");
            item.textContent = `${stop.stop_number}. ${stop.bin_id} `;
            const details = document.createElement("span");
            details.textContent = `· ${stop.priority} priority · fill ${stop.fill_level}/10 · ${Number(stop.distance_from_previous_km).toFixed(2)} km from previous`;
            item.appendChild(details);
            list.appendChild(item);
        });
        const returnItem = document.createElement("li");
        returnItem.textContent = "Return to depot";
        list.appendChild(returnItem);
    }

    renderCityMapLayers();
    if (!routeMap || typeof L === "undefined") return;
    routeMapLayers.forEach(layer => routeMap.removeLayer(layer));
    routeMapLayers = [];
    const points = [
        [route.depot.latitude, route.depot.longitude],
        ...route.stops.map(stop => [stop.latitude, stop.longitude]),
        [route.depot.latitude, route.depot.longitude]
    ];
    const line = L.polyline(points, { color: "#2F7D68", weight: 4, opacity: 0.9 }).addTo(routeMap);
    routeMapLayers.push(line);
    const depotMarker = L.marker(points[0], {
        icon: L.divIcon({ className: "", html: '<span class="route-map-marker depot">D</span>', iconSize: [25, 25], iconAnchor: [12, 12] })
    }).bindPopup(document.createTextNode(`${route.depot.name} (illustrative depot)`)).addTo(routeMap);
    routeMapLayers.push(depotMarker);
    route.stops.forEach(stop => {
        const marker = L.marker([stop.latitude, stop.longitude], {
            icon: L.divIcon({ className: "", html: `<span class="route-map-marker">${stop.stop_number}</span>`, iconSize: [25, 25], iconAnchor: [12, 12] })
        }).bindPopup(document.createTextNode(`${stop.stop_number}. ${stop.bin_id} · ${stop.priority} priority`)).addTo(routeMap);
        routeMapLayers.push(marker);
    });
    routeMap.fitBounds(line.getBounds(), { padding: [24, 24] });
    updateText("routeMapStatus", `${route.number_of_stops} illustrative stops · straight-line route`);
}

// ========================================
// CITIZEN COMPLAINTS
// ========================================

const complaintForm = document.getElementById("citizenComplaintForm");
const complaintImageInput = document.getElementById("complaintImage");
const MAX_COMPLAINT_IMAGE_BYTES = 5 * 1024 * 1024;
const COMPLAINT_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const COMPLAINT_STATUSES = [
    "Submitted",
    "Under Review",
    "In Progress",
    "Resolved",
    "Rejected"
];
let complaintPreviewUrl = null;

function setComplaintError(message) {
    const error = document.getElementById("complaintFormError");
    const success = document.getElementById("complaintFormSuccess");
    if (error) {
        error.textContent = message;
        error.hidden = !message;
    }
    if (success) success.hidden = true;
}

function updateComplaintImagePreview(file) {
    const preview = document.getElementById("complaintImagePreview");
    const image = document.getElementById("complaintImagePreviewImg");
    if (complaintPreviewUrl) {
        URL.revokeObjectURL(complaintPreviewUrl);
        complaintPreviewUrl = null;
    }
    if (!file || !preview || !image) {
        if (preview) preview.hidden = true;
        return;
    }
    complaintPreviewUrl = URL.createObjectURL(file);
    image.src = complaintPreviewUrl;
    preview.hidden = false;
}

function complaintFieldValue(form, name) {
    const field = form.elements.namedItem(name);
    return field ? field.value.trim() : "";
}

function complaintApiError(payload, statusCode) {
    return typeof payload?.detail === "string"
        ? payload.detail
        : `Complaint request failed (${statusCode}).`;
}

async function fetchComplaintList(filters = "") {
    const response = await fetch(`${API_BASE_URL}/api/v1/complaints${filters}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(complaintApiError(payload, response.status));
    return payload;
}

function complaintCell(text, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text;
    return cell;
}

function renderAnalyticsBars(containerId, values) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.replaceChildren();
    if (!values.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state compact-empty";
        empty.textContent = "No complaint records are stored yet.";
        container.appendChild(empty);
        return;
    }

    const maximum = Math.max(...values.map(item => item.count), 1);
    values.forEach(item => {
        const row = document.createElement("div");
        row.className = "analytics-bar-row";
        const label = document.createElement("span");
        label.textContent = item.label;
        const track = document.createElement("span");
        track.className = "analytics-bar-track";
        const fill = document.createElement("i");
        fill.setAttribute("style", `width:${Math.max(3, (item.count / maximum) * 100)}%`);
        track.appendChild(fill);
        const count = document.createElement("strong");
        count.textContent = String(item.count);
        row.appendChild(label);
        row.appendChild(track);
        row.appendChild(count);
        container.appendChild(row);
    });
}

function renderComplaintAnalytics(records) {
    const categories = [
        "Garbage Overflow",
        "Uncollected Waste",
        "Illegal Dumping",
        "Damaged Dustbin",
        "Other"
    ];
    const statuses = ["Submitted", "Under Review", "In Progress", "Resolved", "Rejected"];
    renderAnalyticsBars(
        "complaintCategoryChart",
        records.length
            ? categories.map(label => ({
                label,
                count: records.filter(item => item.category === label).length
            }))
            : []
    );
    renderAnalyticsBars(
        "complaintStatusChart",
        records.length
            ? statuses.map(label => ({
                label,
                count: records.filter(item => item.status === label).length
            }))
            : []
    );

    const resolved = records.filter(item => item.status === "Resolved").length;
    updateText(
        "resolutionRate",
        records.length ? `${Math.round((resolved / records.length) * 100)}%` : "—"
    );
    updateText(
        "resolutionSummaryNote",
        records.length ? `${resolved} of ${records.length} stored complaints resolved` : "No database records"
    );

    const monthlyCounts = new Map();
    records.forEach(record => {
        const match = /^(\d{4})-(\d{2})/.exec(String(record.created_at || ""));
        if (!match) return;
        const key = `${match[1]}-${match[2]}`;
        monthlyCounts.set(key, (monthlyCounts.get(key) || 0) + 1);
    });
    const months = Array.from(monthlyCounts.entries())
        .sort(([first], [second]) => first.localeCompare(second))
        .slice(-8)
        .map(([key, count]) => {
            const [year, month] = key.split("-");
            const date = new Date(Date.UTC(Number(year), Number(month) - 1, 1));
            return {
                label: new Intl.DateTimeFormat("en", {
                    month: "short",
                    year: "2-digit",
                    timeZone: "UTC"
                }).format(date),
                count
            };
        });
    renderAnalyticsBars("complaintTrendChart", months);
}

function renderRecentComplaints(records) {
    const container = document.getElementById("recentComplaints");
    if (!container) return;
    container.replaceChildren();
    if (!records.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state compact-empty";
        empty.textContent = "No citizen complaints have been stored yet.";
        container.appendChild(empty);
        return;
    }

    records.slice(0, 4).forEach(record => {
        const item = document.createElement("div");
        item.className = "recent-complaint-item";
        const marker = document.createElement("span");
        marker.className = "recent-complaint-marker";
        marker.textContent = "▧";
        const content = document.createElement("span");
        const title = document.createElement("strong");
        title.textContent = `${record.category} · ${record.location}`;
        const meta = document.createElement("small");
        const date = new Date(record.created_at);
        const dateLabel = Number.isNaN(date.getTime())
            ? "Date unavailable"
            : new Intl.DateTimeFormat("en-IN", {
                day: "2-digit",
                month: "short",
                year: "numeric"
            }).format(date);
        meta.textContent = `${record.complaint_id} · ${record.status} · ${dateLabel}`;
        content.appendChild(title);
        content.appendChild(meta);
        item.appendChild(marker);
        item.appendChild(content);
        container.appendChild(item);
    });
}

function renderComplaintRows(complaints) {
    const body = document.getElementById("complaintTableBody");
    const emptyState = document.getElementById("complaintEmptyState");
    if (!body) return;
    currentComplaintRows = complaints;
    const searchQuery = document.getElementById("complaintSearch")?.value.trim().toLowerCase() || "";
    const filteredComplaints = complaints.filter(complaint =>
        !searchQuery
        || [
            complaint.complaint_id,
            complaint.category,
            complaint.location,
            complaint.citizen_name,
            complaint.description
        ].some(value => String(value || "").toLowerCase().includes(searchQuery))
    );
    body.replaceChildren();
    if (emptyState) {
        emptyState.hidden = filteredComplaints.length > 0;
        emptyState.textContent = searchQuery && complaints.length
            ? "No stored complaints match your search."
            : "No complaints match this view. Newly submitted records will appear here.";
    }

    filteredComplaints.forEach(complaint => {
        const row = document.createElement("tr");
        const idCell = document.createElement("td");
        const id = document.createElement("strong");
        id.textContent = complaint.complaint_id;
        idCell.appendChild(id);
        row.appendChild(idCell);

        const categoryCell = document.createElement("td");
        categoryCell.textContent = complaint.category;
        const location = document.createElement("small");
        location.textContent = complaint.location;
        categoryCell.appendChild(location);
        row.appendChild(categoryCell);

        const created = new Date(complaint.created_at);
        row.appendChild(complaintCell(
            Number.isNaN(created.getTime())
                ? "Date unavailable"
                : new Intl.DateTimeFormat("en-IN", {
                    day: "2-digit",
                    month: "short",
                    year: "numeric"
                }).format(created)
        ));
        row.appendChild(complaintCell(complaint.priority));

        const statusCell = document.createElement("td");
        statusCell.textContent = complaint.status;
        row.appendChild(statusCell);

        const actions = document.createElement("td");
        actions.className = "complaint-actions";
        const detailsButton = document.createElement("button");
        detailsButton.type = "button";
        detailsButton.className = "outline-button";
        detailsButton.textContent = "Details";
        detailsButton.addEventListener("click", () => void showComplaintDetails(complaint.complaint_id));
        actions.appendChild(detailsButton);

        const statusSelect = document.createElement("select");
        statusSelect.className = "complaint-status-select";
        statusSelect.setAttribute("aria-label", `Update status for ${complaint.complaint_id}`);
        COMPLAINT_STATUSES.forEach(status => {
            const option = document.createElement("option");
            option.value = status;
            option.textContent = status;
            option.selected = status === complaint.status;
            statusSelect.appendChild(option);
        });
        actions.appendChild(statusSelect);

        const updateButton = document.createElement("button");
        updateButton.type = "button";
        updateButton.className = "outline-button";
        updateButton.textContent = "Update";
        updateButton.addEventListener("click", () => {
            void updateComplaintStatus(complaint.complaint_id, statusSelect.value, updateButton);
        });
        actions.appendChild(updateButton);
        row.appendChild(actions);
        body.appendChild(row);
    });
}

async function loadComplaints() {
    const error = document.getElementById("complaintAdminError");
    if (error) {
        error.textContent = "";
        error.hidden = true;
    }
    const statusFilter = document.getElementById("complaintStatusFilter")?.value || "";
    const categoryFilter = document.getElementById("complaintCategoryFilter")?.value || "";
    const priorityFilter = document.getElementById("complaintPriorityFilter")?.value || "";
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    if (priorityFilter) params.set("priority", priorityFilter);
    const filters = params.size ? `?${params.toString()}` : "";

    try {
        const [allRecords, visibleRecords] = filters
            ? await Promise.all([fetchComplaintList(), fetchComplaintList(filters)])
            : await (async () => {
                const records = await fetchComplaintList();
                return [records, records];
            })();
        const records = allRecords.complaints || [];
        complaintRecords = records;
        updateText("complaintTotal", String(records.length));
        updateText("overviewComplaintTotal", String(records.length));
        updateText("complaintSubmitted", String(records.filter(item => item.status === "Submitted").length));
        updateText("complaintInProgress", String(records.filter(item => item.status === "In Progress").length));
        updateText("complaintResolved", String(records.filter(item => item.status === "Resolved").length));
        renderComplaintAnalytics(records);
        renderRecentComplaints(records);
        renderComplaintRows(visibleRecords.complaints || []);
        renderCityMapLayers();
    } catch (requestError) {
        if (error) {
            error.textContent = requestError.message || "Unable to load complaints from the database.";
            error.hidden = false;
        }
        updateText("complaintTotal", "—");
        updateText("overviewComplaintTotal", "—");
        updateText("complaintSubmitted", "—");
        updateText("complaintInProgress", "—");
        updateText("complaintResolved", "—");
        complaintRecords = [];
        renderComplaintAnalytics([]);
        const recent = document.getElementById("recentComplaints");
        if (recent) {
            recent.replaceChildren();
            const empty = document.createElement("div");
            empty.className = "empty-state compact-empty";
            empty.textContent = "Complaint records could not be loaded from SQLite.";
            recent.appendChild(empty);
        }
        renderComplaintRows([]);
        renderCityMapLayers();
    }
}

async function showComplaintDetails(complaintId) {
    const detail = document.getElementById("complaintDetail");
    try {
        const response = await fetch(`${API_BASE_URL}/api/v1/complaints/${encodeURIComponent(complaintId)}`);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(complaintApiError(payload, response.status));
        updateText("complaintDetailId", `ID: ${payload.complaint_id}`);
        updateText("complaintDetailCitizen", `Citizen: ${payload.citizen_name}`);
        updateText("complaintDetailContact", `Contact: ${payload.contact}`);
        updateText("complaintDetailDescription", payload.description);
        const imageLink = document.getElementById("complaintDetailImage");
        if (imageLink) {
            imageLink.hidden = !payload.image_path;
            imageLink.href = `${API_BASE_URL}/api/v1/complaints/${encodeURIComponent(complaintId)}/image`;
        }
        if (detail) detail.hidden = false;
    } catch (requestError) {
        const error = document.getElementById("complaintAdminError");
        if (error) {
            error.textContent = requestError.message || "Unable to load complaint details.";
            error.hidden = false;
        }
    }
}

async function updateComplaintStatus(complaintId, status, button) {
    button.disabled = true;
    try {
        const response = await fetch(
            `${API_BASE_URL}/api/v1/complaints/${encodeURIComponent(complaintId)}/status`,
            {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status })
            }
        );
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(complaintApiError(payload, response.status));
        await loadComplaints();
        showToast(`Complaint ${complaintId} updated.`);
    } catch (error) {
        const adminError = document.getElementById("complaintAdminError");
        if (adminError) {
            adminError.textContent = error.message || "Unable to update complaint status.";
            adminError.hidden = false;
        }
    } finally {
        button.disabled = false;
    }
}

if (complaintImageInput) {
    complaintImageInput.addEventListener("change", () => {
        const file = complaintImageInput.files?.[0];
        updateComplaintImagePreview(file);
        setComplaintError("");
        if (!file) return;
        if (!COMPLAINT_IMAGE_TYPES.includes(file.type)) {
            setComplaintError("Choose a JPEG, PNG, or WebP image.");
        } else if (file.size > MAX_COMPLAINT_IMAGE_BYTES) {
            setComplaintError("Image exceeds the 5 MB upload limit.");
        }
    });
}

if (complaintForm) {
    complaintForm.addEventListener("submit", async event => {
        event.preventDefault();
        setComplaintError("");
        const success = document.getElementById("complaintFormSuccess");
        if (success) success.hidden = true;
        const image = complaintImageInput?.files?.[0];
        if (image && !COMPLAINT_IMAGE_TYPES.includes(image.type)) {
            setComplaintError("Choose a JPEG, PNG, or WebP image.");
            return;
        }
        if (image && image.size > MAX_COMPLAINT_IMAGE_BYTES) {
            setComplaintError("Image exceeds the 5 MB upload limit.");
            return;
        }

        const latitude = complaintFieldValue(complaintForm, "latitude");
        const longitude = complaintFieldValue(complaintForm, "longitude");
        if (Boolean(latitude) !== Boolean(longitude)) {
            setComplaintError("Enter both latitude and longitude, or leave both empty.");
            return;
        }
        if (latitude && (
            !Number.isFinite(Number(latitude)) || Number(latitude) < -90 || Number(latitude) > 90
            || !Number.isFinite(Number(longitude)) || Number(longitude) < -180 || Number(longitude) > 180
        )) {
            setComplaintError("Enter valid coordinates within latitude -90 to 90 and longitude -180 to 180.");
            return;
        }

        const button = document.getElementById("submitComplaintBtn");
        const formStatus = document.getElementById("complaintFormStatus");
        const formData = new FormData();
        ["citizen_name", "contact", "category", "description", "location", "priority"].forEach(name => {
            formData.append(name, complaintFieldValue(complaintForm, name));
        });
        if (latitude) {
            formData.append("latitude", latitude);
            formData.append("longitude", longitude);
        }
        if (image) formData.append("image", image);
        if (button) {
            button.disabled = true;
            button.textContent = "Submitting...";
        }
        if (formStatus) formStatus.textContent = "Submitting complaint…";

        try {
            const response = await fetch(`${API_BASE_URL}/api/v1/complaints`, {
                method: "POST",
                body: formData
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(complaintApiError(payload, response.status));
            if (success) {
                success.textContent = `Complaint registered successfully. Your complaint ID is ${payload.complaint_id}.`;
                success.hidden = false;
            }
            if (formStatus) formStatus.textContent = "Complaint submitted.";
            complaintForm.reset();
            updateComplaintImagePreview(null);
            await loadComplaints();
        } catch (error) {
            if (formStatus) formStatus.textContent = "Submission failed. You can retry.";
            setComplaintError(error.message || "Unable to submit complaint. Please try again.");
            updateComplaintImagePreview(image);
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = "Submit complaint";
            }
        }
    });
}

document.getElementById("refreshComplaintsBtn")?.addEventListener("click", () => loadComplaints());
document.getElementById("complaintStatusFilter")?.addEventListener("change", () => loadComplaints());
document.getElementById("complaintCategoryFilter")?.addEventListener("change", () => loadComplaints());
document.getElementById("closeComplaintDetailBtn")?.addEventListener("click", () => {
    const detail = document.getElementById("complaintDetail");
    if (detail) detail.hidden = true;
});

const addRouteStopButton = document.getElementById("addRouteStopBtn");
addRouteStopButton?.addEventListener("click", () => {
    const sequence = routeStopSequence++;
    addRouteStopRow({
        bin_id: `DEMO-BIN-${String(sequence).padStart(2, "0")}`,
        latitude: 37.5665 + (sequence % 5) * 0.001,
        longitude: 126.9780 + (sequence % 4) * 0.001,
        fill_level: 5,
        priority: "MEDIUM"
    });
});

document.getElementById("optimizeRouteBtn")?.addEventListener("click", async event => {
    const button = event.currentTarget;
    const errorElement = document.getElementById("routeError");
    const statusElement = document.getElementById("routeStatus");
    const results = document.getElementById("routeResults");
    if (errorElement) {
        errorElement.textContent = "";
        errorElement.hidden = true;
    }
    if (results) results.hidden = true;

    let requestBody;
    try {
        requestBody = collectRouteRequest();
    } catch (error) {
        if (errorElement) {
            errorElement.textContent = error.message;
            errorElement.hidden = false;
        }
        if (statusElement) {
            statusElement.textContent = "Route needs attention.";
            statusElement.classList.add("error");
        }
        return;
    }

    button.disabled = true;
    button.innerHTML = "<span>⌁</span> Optimizing…";
    if (statusElement) {
        statusElement.textContent = "Finding a priority-aware route…";
        statusElement.classList.remove("error");
    }
    try {
        const response = await fetch(`${API_BASE_URL}/api/v1/routes/optimize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || `Route optimization failed (${response.status}).`);
        renderOptimizedRoute(payload);
        if (statusElement) statusElement.textContent = "Illustrative route optimized.";
    } catch (error) {
        console.error("Route optimization failed:", error);
        if (errorElement) {
            errorElement.textContent = error.message || "Unable to optimize this route.";
            errorElement.hidden = false;
        }
        if (statusElement) {
            statusElement.textContent = "Route optimization failed.";
            statusElement.classList.add("error");
        }
    } finally {
        button.disabled = false;
        button.innerHTML = "<span>⌁</span> Optimize route";
    }
});

const routeStopList = document.getElementById("routeStopList");
if (routeStopList) {
    illustrativeRouteStops.forEach(addRouteStopRow);
    initializeRouteMap();
}
initializeCityMap();

document.querySelectorAll(
    "#mapShowBins, #mapShowComplaints, #mapShowRoute"
).forEach(control => {
    control.addEventListener("change", renderCityMapLayers);
});

document.getElementById("viewRouteMapBtn")?.addEventListener("click", () => {
    const routeToggle = document.getElementById("mapShowRoute");
    if (routeToggle) routeToggle.checked = true;
    renderCityMapLayers();
});

function updateWasteImagePreview(file) {
    const preview = document.getElementById("wasteUploadPreview");
    const previewImage = document.getElementById("wastePreviewImage");
    const fileName = document.getElementById("wasteFileName");
    if (wastePreviewUrl) {
        URL.revokeObjectURL(wastePreviewUrl);
        wastePreviewUrl = null;
    }
    if (!file || !preview || !previewImage || !fileName) {
        if (preview) preview.hidden = true;
        return;
    }

    wastePreviewUrl = URL.createObjectURL(file);
    previewImage.src = wastePreviewUrl;
    fileName.textContent = file.name;
    preview.hidden = false;
}

if (wasteImageInput) {
    wasteImageInput.addEventListener("change", () => {
        setWasteAnalysisError("");
        resetWasteAnalysisResult();
        const file = wasteImageInput.files?.[0];
        updateWasteImagePreview(file);
        if (!file) return;

        if (!WASTE_IMAGE_TYPES.includes(file.type)) {
            setWasteAnalysisError("Choose a JPEG, PNG, or WebP image.");
            wasteImageInput.value = "";
            updateWasteImagePreview(null);
            return;
        }
        if (file.size > MAX_WASTE_IMAGE_BYTES) {
            setWasteAnalysisError("Image exceeds the 8 MB upload limit.");
            wasteImageInput.value = "";
            updateWasteImagePreview(null);
        }
    });
}

const wasteDropZone = document.getElementById("wasteDropZone");
if (wasteDropZone) {
    ["dragenter", "dragover"].forEach(eventName => {
        wasteDropZone.addEventListener(eventName, event => {
            event.preventDefault();
            wasteDropZone.classList.add("is-dragging");
        });
    });
    ["dragleave", "drop"].forEach(eventName => {
        wasteDropZone.addEventListener(eventName, event => {
            event.preventDefault();
            wasteDropZone.classList.remove("is-dragging");
        });
    });
    wasteDropZone.addEventListener("drop", event => {
        const file = event.dataTransfer?.files?.[0];
        if (!file || !wasteImageInput) return;
        if (!WASTE_IMAGE_TYPES.includes(file.type)) {
            setWasteAnalysisError("Choose a JPEG, PNG, or WebP image.");
            return;
        }
        if (file.size > MAX_WASTE_IMAGE_BYTES) {
            setWasteAnalysisError("Image exceeds the 8 MB upload limit.");
            return;
        }
        const transfer = new DataTransfer();
        transfer.items.add(file);
        wasteImageInput.files = transfer.files;
        wasteImageInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
}

if (wasteAnalysisForm && wasteImageInput && analyzeWasteButton) {
    wasteAnalysisForm.addEventListener("submit", async event => {
        event.preventDefault();
        setWasteAnalysisError("");
        resetWasteAnalysisResult();
        const file = wasteImageInput.files?.[0];
        if (!file) {
            setWasteAnalysisError("Select an image before starting the analysis.");
            return;
        }

        analyzeWasteButton.disabled = true;
        analyzeWasteButton.textContent = "Analyzing image...";
        updateText("wasteAnalysisStatus", "Uploading image for analysis...");

        try {
            const formData = new FormData();
            formData.append("image", file);
            const response = await fetch(`${API_BASE_URL}/api/v1/waste/analyze`, {
                method: "POST",
                body: formData
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                if (response.status === 503 && response.headers.get("Retry-After")) {
                    throw new Error(WASTE_ANALYSIS_BUSY_MESSAGE);
                }
                throw new Error(payload.detail || `Analysis request failed (${response.status}).`);
            }

            displayWasteAnalysis(payload);
            updateText("wasteAnalysisStatus", "Analysis complete.");
        } catch (error) {
            console.error("Waste image analysis failed:", error);
            updateWasteImagePreview(file);
            setWasteAnalysisError(error.message || "Unable to analyze this image. Please try again.");
        } finally {
            analyzeWasteButton.disabled = false;
            analyzeWasteButton.innerHTML = "<span>✦</span> Analyze image";
        }
    });
}

// ========================================
// DASHBOARD INITIALIZATION
// ========================================

async function loadDashboard() {
    updateText("apiStatus", "Connecting…");
    updateText("systemStatus", "CONNECTING");
    setPredictionState("Loading historical estimate…", "loading");

    const results = await Promise.allSettled([
        loadHealth(),
        loadBins(),
        loadHistory()
    ]);

    if (results[0].status === "rejected") {
        console.error("API health check failed:", results[0].reason);
        updateText("apiStatus", "Unavailable");
        updateText("systemStatus", "API OFFLINE");
        updateText("settingsApiStatus", "Unavailable");
        updateText("settingsApiDetails", "The health endpoint could not be reached.");
        ["apiDot", "settingsApiDot"].forEach(id => {
            document.getElementById(id)?.classList.add("is-disconnected");
        });
    }

    if (results[1].status === "rejected") {
        console.error("Bin inventory failed:", results[1].reason);
        updateText("totalBins", "—");
        updateText("navBinCount", "—");
        updateText("totalRecords", "—");
        updateText("predictionDatasetCount", "—");
        updateText("binRecordCount", "—");
        updateText("latestFill", "—");
        updateText("overviewLatestFill", "—");
        updateText("lastObservation", "Unavailable");
        updateText("overviewLatestDate", "Unavailable");
    }

    if (results[2].status === "rejected") {
        console.error("Historical observations failed:", results[2].reason);
        clearHistoryChart("Unable to load historical observations from the bins history endpoint.");
    }

    try {
        await loadPrediction();
    } catch (predictionError) {
        console.error("Prediction failed:", predictionError);
        clearPredictionDetails();
        setPredictionState("Prediction unavailable", "error");
    }

    const hasFailure = results.some(result => result.status === "rejected");
    showToast(
        hasFailure
            ? "Some data sources are unavailable. Review their status in the workspace."
            : "Workspace data refreshed."
    );
    return results;
}

// ========================================
// MANUAL PREDICTION BUTTON
// ========================================

async function requestPrediction(button) {
    if (button) {
        button.disabled = true;
        button.textContent = "Generating estimate…";
    }
    try {
        await loadPrediction();
        showToast("Historical estimate generated.");
    } catch (error) {
        console.error("Prediction failed:", error);
        clearPredictionDetails();
        setPredictionState("Prediction unavailable", "error");
        showToast("Prediction unavailable. Check the backend connection.");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = button.id === "binGeneratePredictionBtn"
                ? "Refresh estimate"
                : "Generate estimate";
        }
    }
}

predictionBtn?.addEventListener("click", event => requestPrediction(event.currentTarget));
document.getElementById("binGeneratePredictionBtn")?.addEventListener(
    "click",
    event => requestPrediction(event.currentTarget)
);

// ========================================
// REFRESH DASHBOARD
// ========================================

refreshButton?.addEventListener("click", async () => {
    refreshButton.disabled = true;
    refreshButton.innerHTML = "<span>↻</span> Refreshing…";
    try {
        await Promise.all([loadDashboard(), loadComplaints()]);
    } finally {
        refreshButton.disabled = false;
        refreshButton.innerHTML = "<span>↻</span> Refresh data";
    }
});

function closeMobileNavigation() {
    sidebar?.classList.remove("open");
    document.getElementById("appShell")?.classList.remove("mobile-menu-open");
    menuToggle?.setAttribute("aria-expanded", "false");
}

menuToggle?.addEventListener("click", () => {
    const isOpen = sidebar?.classList.toggle("open") || false;
    document.getElementById("appShell")?.classList.toggle("mobile-menu-open", isOpen);
    menuToggle.setAttribute("aria-expanded", String(isOpen));
});

document.getElementById("sidebarScrim")?.addEventListener("click", closeMobileNavigation);
document.getElementById("sidebarCollapseBtn")?.addEventListener("click", event => {
    const shell = document.getElementById("appShell");
    if (!shell) return;
    const collapsed = shell.classList.toggle("sidebar-collapsed");
    event.currentTarget.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
    event.currentTarget.textContent = collapsed ? "›" : "‹";
});

function activateSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    document.querySelectorAll(".nav-item").forEach(item => {
        const active = item.dataset.section === sectionId;
        item.classList.toggle("active", active);
        if (active) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
    });
    updateText("currentSectionTitle", section.dataset.pageTitle || "Overview");
}

document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
        activateSection(item.dataset.section);
        if (window.innerWidth <= 760) closeMobileNavigation();
    });
});

window.addEventListener?.("hashchange", () => {
    activateSection(window.location.hash.slice(1) || "overview");
});

if (typeof IntersectionObserver !== "undefined") {
    const sectionObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) activateSection(entry.target.id);
        });
    }, { rootMargin: "-18% 0px -65% 0px", threshold: 0 });
    document.querySelectorAll(".page-section").forEach(section => sectionObserver.observe(section));
}

const initialSection = window.location?.hash.slice(1) || "overview";
activateSection(initialSection);

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
    () => {
        void loadDashboard();
        void loadComplaints();
    }
);