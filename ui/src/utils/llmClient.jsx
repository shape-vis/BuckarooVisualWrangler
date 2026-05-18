// Thin client for the LLM orchestration endpoints.
// Frontend never talks to Ollama directly; it goes through the Flask backend
// which calls Ollama and returns structured JSON.

export async function analyzeNode(nodeTable) {
    const res = await fetch("/api/llm/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable }),
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`analyze failed: ${res.status} ${text}`);
    }
    return res.json();
}

export async function previewProposal(nodeTable, proposal) {
    const res = await fetch("/api/llm/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable, proposal }),
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`preview failed: ${res.status} ${text}`);
    }
    return res.json();
}

export async function materializeProposal(nodeTable, proposal) {
    const res = await fetch("/api/llm/materialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable, proposal }),
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`materialize failed: ${res.status} ${text}`);
    }
    return res.json();
}

export async function materializePlan(nodeTable, plan) {
    const res = await fetch("/api/llm/materialize-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable, plan }),
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`materialize-plan failed: ${res.status} ${text}`);
    }
    return res.json();
}

export async function previewPlan(nodeTable, plan) {
    const res = await fetch("/api/llm/preview-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable, plan }),
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`preview-plan failed: ${res.status} ${text}`);
    }
    return res.json();
}
