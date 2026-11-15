const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const BUSY_MESSAGE =
    "AI image analysis is temporarily busy. Please try again in a few minutes.";

function createDashboard(response) {
    const elements = new Map();
    const makeElement = () => ({
        hidden: false,
        textContent: "",
        innerHTML: "",
        value: "",
        disabled: false,
        files: [],
        listeners: {},
        classList: {
            add() {},
            remove() {},
            toggle() {}
        },
        addEventListener(event, callback) {
            this.listeners[event] = callback;
        }
    });

    for (const id of [
        "wasteAnalysisForm",
        "wasteImage",
        "analyzeWasteBtn",
        "wasteAnalysisError",
        "wasteAnalysisStatus",
        "wasteAnalysisResult",
        "wasteSeverity",
        "wasteUncertainty",
        "wasteUploadPreview",
        "wastePreviewImage",
        "wasteFileName"
    ]) {
        elements.set(id, makeElement());
    }

    elements.get("wasteImage").files = [{
        name: "test-waste.png",
        type: "image/png",
        size: 128
    }];

    const document = {
        getElementById(id) {
            return elements.get(id);
        },
        querySelectorAll() {
            return [];
        },
        addEventListener() {}
    };
    const context = {
        document,
        window: { innerWidth: 1024 },
        URL: {
            createObjectURL: () => "blob:test-preview",
            revokeObjectURL() {}
        },
        FormData: class {
            append() {}
        },
        fetch: async () => response,
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

async function submitWasteAnalysis(elements) {
    const submit = elements.get("wasteAnalysisForm").listeners.submit;
    await submit({ preventDefault() {} });
}

test("overload response displays busy message and preserves preview for retry", async () => {
    const elements = createDashboard({
        ok: false,
        status: 503,
        headers: { get: name => name === "Retry-After" ? "300" : null },
        json: async () => ({ detail: "server detail" })
    });

    await submitWasteAnalysis(elements);

    assert.equal(elements.get("wasteAnalysisError").textContent, BUSY_MESSAGE);
    assert.equal(elements.get("wasteUploadPreview").hidden, false);
    assert.equal(elements.get("wastePreviewImage").src, "blob:test-preview");
    assert.equal(elements.get("wasteFileName").textContent, "test-waste.png");
    assert.equal(elements.get("wasteImage").files.length, 1);
    assert.equal(elements.get("analyzeWasteBtn").disabled, false);
});

test("non-overload configuration 503 displays its API detail", async () => {
    const elements = createDashboard({
        ok: false,
        status: 503,
        headers: { get: () => null },
        json: async () => ({ detail: "Waste analysis is not configured on the server." })
    });

    await submitWasteAnalysis(elements);

    assert.equal(
        elements.get("wasteAnalysisError").textContent,
        "Waste analysis is not configured on the server."
    );
    assert.equal(elements.get("wasteUploadPreview").hidden, false);
    assert.equal(elements.get("wasteImage").files.length, 1);
});
