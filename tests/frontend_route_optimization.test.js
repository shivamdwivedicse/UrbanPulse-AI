const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class Element {
    constructor(id = "", className = "") {
        this.id = id;
        this.children = [];
        this.listeners = {};
        this.dataset = {};
        this.classNames = new Set();
        this.className = className;
        this.classList = {
            add: name => this.classNames.add(name),
            remove: name => this.classNames.delete(name),
            toggle: (name, force) => {
                if (force) this.classNames.add(name);
                else this.classNames.delete(name);
            }
        };
        this.hidden = false;
        this.disabled = false;
        this.value = "";
        this.textContent = "";
        this.innerHTML = "";
        this.required = false;
        this.attributes = {};
    }

    get className() {
        return Array.from(this.classNames).join(" ");
    }

    set className(value) {
        this.classNames = new Set(String(value).split(/\s+/).filter(Boolean));
    }

    addEventListener(event, callback) {
        this.listeners[event] = callback;
    }

    appendChild(child) {
        child.parent = this;
        this.children.push(child);
        return child;
    }

    remove() {
        if (this.parent) {
            this.parent.children = this.parent.children.filter(child => child !== this);
        }
    }

    replaceChildren(...children) {
        this.children = [];
        children.forEach(child => this.appendChild(child));
    }

    setAttribute(name, value) {
        this.attributes[name] = value;
    }

    querySelectorAll(selector) {
        if (selector === "[data-field]") {
            return this.children.flatMap(child => [
                ...(child.dataset.field ? [child] : []),
                ...child.querySelectorAll(selector)
            ]);
        }
        if (selector === "#routeStopList .route-stop-row") {
            return this.children.filter(child => child.classNames.has("route-stop-row"));
        }
        return [];
    }
}

function createRouteDashboard(fetchImplementation) {
    const ids = [
        "routeStopList",
        "routeStopCount",
        "routeDepotName",
        "routeDepotLatitude",
        "routeDepotLongitude",
        "routeResults",
        "routeDistance",
        "routeResultStopCount",
        "routeOptimizationStatus",
        "routeMethodology",
        "routeOrderedStops",
        "routeMap",
        "routeMapStatus",
        "routeError",
        "routeStatus",
        "addRouteStopBtn",
        "optimizeRouteBtn"
    ];
    const elements = new Map(ids.map(id => [id, new Element(id)]));
    elements.get("routeDepotName").value = "Illustrative depot";
    elements.get("routeDepotLatitude").value = "37.5665";
    elements.get("routeDepotLongitude").value = "126.978";

    const document = {
        getElementById: id => elements.get(id) || null,
        createElement: tag => new Element("", tag),
        createTextNode: text => ({ textContent: text }),
        querySelectorAll(selector) {
            if (selector === "#routeStopList .route-stop-row") {
                return elements.get("routeStopList").children.filter(
                    child => child.classNames.has("route-stop-row")
                );
            }
            return [];
        },
        addEventListener() {}
    };

    const map = {
        setView() { return this; },
        fitBounds() {},
        removeLayer() {}
    };
    const layer = {
        addTo() { return this; },
        bindPopup() { return this; },
        getBounds() { return {}; }
    };
    const L = {
        map: () => map,
        tileLayer: () => layer,
        polyline: () => layer,
        marker: () => layer,
        divIcon: options => options
    };
    const context = {
        document,
        window: { innerWidth: 1024 },
        L,
        fetch: fetchImplementation,
        console: { error() {} },
        Intl,
        Date,
        setTimeout,
        clearTimeout
    };
    const sourcePath = path.join(__dirname, "..", "frontend", "assets", "js", "app.js");
    vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context);
    return elements;
}

async function optimizeRoute(elements) {
    await elements.get("optimizeRouteBtn").listeners.click({
        currentTarget: elements.get("optimizeRouteBtn")
    });
}

test("route optimizer submits editable sample stops and renders result", async () => {
    let submittedBody;
    const elements = createRouteDashboard(async (_url, options) => {
        submittedBody = JSON.parse(options.body);
        const orderedStops = [...submittedBody.stops].sort(
            (left, right) => ["HIGH", "MEDIUM", "LOW"].indexOf(left.priority)
                - ["HIGH", "MEDIUM", "LOW"].indexOf(right.priority)
        );
        return {
            ok: true,
            json: async () => ({
                depot: submittedBody.depot,
                stops: orderedStops.map((stop, index) => ({
                    ...stop,
                    stop_number: index + 1,
                    distance_from_previous_km: 0.3
                })),
                total_estimated_distance_km: 1.24,
                number_of_stops: orderedStops.length,
                optimization_status: "SOLUTION_FOUND",
                distance_methodology: "Haversine straight-line distance.",
                return_to_depot: true
            })
        };
    });

    assert.equal(elements.get("routeStopList").children.length, 4);
    elements.get("addRouteStopBtn").listeners.click();
    assert.equal(elements.get("routeStopList").children.length, 5);

    await optimizeRoute(elements);

    assert.equal(submittedBody.stops.length, 5);
    assert.equal(submittedBody.stops[4].bin_id, "DEMO-BIN-05");
    assert.equal(elements.get("routeResults").hidden, false);
    assert.equal(elements.get("routeDistance").textContent, "1.24 km");
    assert.equal(elements.get("routeResultStopCount").textContent, "5");
    assert.equal(elements.get("routeOrderedStops").children.length, 6);
    assert.equal(elements.get("routeStatus").textContent, "Illustrative route optimized.");
    assert.equal(elements.get("routeError").hidden, true);
});

test("route optimizer reports empty stop state without making an API request", async () => {
    let fetchCalled = false;
    const elements = createRouteDashboard(async () => {
        fetchCalled = true;
        throw new Error("unexpected request");
    });
    elements.get("routeStopList").children.slice().forEach(row => row.remove());

    await optimizeRoute(elements);

    assert.equal(fetchCalled, false);
    assert.equal(elements.get("routeError").textContent, "Add at least one collection stop.");
    assert.equal(elements.get("routeError").hidden, false);
});

test("route optimizer shows API errors and restores its action", async () => {
    const elements = createRouteDashboard(async () => ({
        ok: false,
        status: 422,
        json: async () => ({ detail: "No feasible route was found." })
    }));

    await optimizeRoute(elements);

    assert.equal(elements.get("routeError").textContent, "No feasible route was found.");
    assert.equal(elements.get("routeError").hidden, false);
    assert.equal(elements.get("routeStatus").textContent, "Route optimization failed.");
    assert.equal(elements.get("optimizeRouteBtn").disabled, false);
});
