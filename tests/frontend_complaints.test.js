const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class Element {
    constructor(id = "") {
        this.id = id;
        this.children = [];
        this.listeners = {};
        this.attributes = {};
        this.hidden = false;
        this.disabled = false;
        this.textContent = "";
        this.value = "";
        this.files = [];
        this.className = "";
        this.dataset = {};
        this.classList = { add() {}, remove() {}, toggle() {} };
        this.elements = { namedItem: name => this.fields?.[name] || null };
    }

    addEventListener(event, callback) {
        this.listeners[event] = callback;
    }

    appendChild(child) {
        child.parent = this;
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = [];
        children.forEach(child => this.appendChild(child));
    }

    setAttribute(name, value) {
        this.attributes[name] = value;
    }

    reset() {
        Object.values(this.fields || {}).forEach(field => { field.value = ""; });
        const image = this.fields?.image;
        if (image) image.files = [];
    }
}

class TestFormData {
    constructor() {
        this.values = [];
    }
    append(name, value) {
        this.values.push([name, value]);
    }
}

function createDashboard(fetchImplementation) {
    const ids = [
        "citizenComplaintForm",
        "complaintImage",
        "complaintImagePreview",
        "complaintImagePreviewImg",
        "complaintFormError",
        "complaintFormSuccess",
        "complaintFormStatus",
        "submitComplaintBtn",
        "complaintAdminError",
        "complaintTableBody",
        "complaintEmptyState",
        "complaintTotal",
        "complaintSubmitted",
        "complaintInProgress",
        "complaintResolved",
        "complaintStatusFilter",
        "complaintCategoryFilter",
        "refreshComplaintsBtn",
        "complaintDetail",
        "complaintDetailImage",
        "complaintDetailId",
        "complaintDetailCitizen",
        "complaintDetailContact",
        "complaintDetailDescription",
        "closeComplaintDetailBtn"
    ];
    const elements = new Map(ids.map(id => [id, new Element(id)]));
    const form = elements.get("citizenComplaintForm");
    form.fields = {
        citizen_name: { value: "Asha Citizen" },
        contact: { value: "asha@example.test" },
        category: { value: "Garbage Overflow" },
        description: { value: "Overflow has continued near the community park." },
        location: { value: "Community park entrance" },
        priority: { value: "High" },
        latitude: { value: "" },
        longitude: { value: "" },
        image: elements.get("complaintImage")
    };
    const document = {
        getElementById: id => elements.get(id) || null,
        createElement: () => new Element(),
        querySelectorAll: () => [],
        addEventListener() {}
    };
    const context = {
        document,
        window: { innerWidth: 1024 },
        fetch: fetchImplementation,
        FormData: TestFormData,
        URL: {
            createObjectURL: () => "blob:complaint-preview",
            revokeObjectURL() {}
        },
        URLSearchParams,
        Intl,
        Date,
        setTimeout,
        clearTimeout,
        console: { error() {} }
    };
    const sourcePath = path.join(__dirname, "..", "frontend", "assets", "js", "app.js");
    vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context);
    return elements;
}

test("citizen submission sends form data and shows the database-generated ID", async () => {
    let requestBody;
    let requestCount = 0;
    const elements = createDashboard(async (_url, options) => {
        requestCount += 1;
        if (options?.method === "POST") {
            requestBody = options.body;
            return { ok: true, json: async () => ({ complaint_id: "CMP-A1B2C3D4E5F6" }) };
        }
        return { ok: true, json: async () => ({ total: 0, complaints: [] }) };
    });

    await elements.get("citizenComplaintForm").listeners.submit({
        preventDefault() {}
    });

    assert.equal(requestCount, 2);
    assert.ok(requestBody instanceof TestFormData);
    assert.ok(requestBody.values.some(([name, value]) => name === "category" && value === "Garbage Overflow"));
    assert.equal(
        elements.get("complaintFormSuccess").textContent,
        "Complaint registered successfully. Your complaint ID is CMP-A1B2C3D4E5F6."
    );
    assert.equal(elements.get("complaintFormSuccess").hidden, false);
    assert.equal(elements.get("submitComplaintBtn").disabled, false);
});

test("failed submission preserves the selected image for retry", async () => {
    const elements = createDashboard(async () => ({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Complaint service unavailable." })
    }));
    const image = { name: "street.png", type: "image/png", size: 12 };
    elements.get("complaintImage").files = [image];

    await elements.get("citizenComplaintForm").listeners.submit({
        preventDefault() {}
    });

    assert.equal(elements.get("complaintImage").files[0], image);
    assert.equal(elements.get("complaintImagePreview").hidden, false);
    assert.equal(elements.get("complaintFormError").textContent, "Complaint service unavailable.");
    assert.equal(elements.get("complaintFormError").hidden, false);
});

test("admin list shows real database rows and summary counts", async () => {
    const complaint = {
        complaint_id: "CMP-A1B2C3D4E5F6",
        category: "Illegal Dumping",
        location: "River path",
        created_at: "2025-01-02T03:04:05+00:00",
        priority: "High",
        status: "In Progress"
    };
    const elements = createDashboard(async () => ({
        ok: true,
        json: async () => ({ total: 1, complaints: [complaint] })
    }));

    await elements.get("refreshComplaintsBtn").listeners.click();

    assert.equal(elements.get("complaintTotal").textContent, "1");
    assert.equal(elements.get("complaintInProgress").textContent, "1");
    assert.equal(elements.get("complaintTableBody").children.length, 1);
    assert.equal(elements.get("complaintEmptyState").hidden, true);
});
