let feedData = {
    prop: [],
    execute: [],
    shadow: [],
    market_map: []
};

let lastFocusedTrigger = null;

document.addEventListener("DOMContentLoaded", () => {
    fetchFeedData();
    setupKeyboardTabs();
    setupModalListeners();
});

async function fetchFeedData() {
    const loadingState = document.getElementById("loading-state");
    const errorState = document.getElementById("error-state");

    try {
        const response = await fetch("/api/feed");
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        feedData = await response.json();
        
        if (loadingState) loadingState.style.display = "none";
        if (errorState) errorState.style.display = "none";

        renderAllTabs();
        renderLiveMarketPulse();
    } catch (error) {
        console.error("Failed to load feed data:", error);
        if (loadingState) loadingState.style.display = "none";
        if (errorState) errorState.style.display = "block";
    }
}

function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.remove("active");
        btn.setAttribute("aria-selected", "false");
        btn.setAttribute("tabindex", "-1");
    });
    document.querySelectorAll(".tab-panel").forEach(panel => {
        panel.classList.remove("active");
    });

    const activeBtn = document.getElementById(`tab-${tabId}`);
    const activePanel = document.getElementById(`${tabId}-panel`);

    if (activeBtn) {
        activeBtn.classList.add("active");
        activeBtn.setAttribute("aria-selected", "true");
        activeBtn.setAttribute("tabindex", "0");
    }
    if (activePanel) {
        activePanel.classList.add("active");
    }
}

function setupKeyboardTabs() {
    const tabList = document.querySelector(".tab-bar");
    if (!tabList) return;

    tabList.addEventListener("keydown", (e) => {
        const tabs = Array.from(tabList.querySelectorAll(".tab-btn"));
        const currentIndex = tabs.findIndex(tab => tab.getAttribute("aria-selected") === "true");

        if (currentIndex === -1) return;

        let newIndex = currentIndex;
        if (e.key === "ArrowRight") {
            newIndex = (currentIndex + 1) % tabs.length;
            e.preventDefault();
        } else if (e.key === "ArrowLeft") {
            newIndex = (currentIndex - 1 + tabs.length) % tabs.length;
            e.preventDefault();
        } else {
            return;
        }

        const targetTab = tabs[newIndex];
        const tabId = targetTab.id.replace("tab-", "");
        switchTab(tabId);
        targetTab.focus();
    });
}

function renderAllTabs() {
    updateCounts();
    renderPropGrid();
    renderExecuteGrid();
    renderShadowGrid();
    renderMarketMapTable();
}

function updateCounts() {
    const countProp = document.getElementById("count-prop");
    const countExecute = document.getElementById("count-execute");
    const countShadow = document.getElementById("count-shadow");
    const countMarketMap = document.getElementById("count-market_map");

    if (countProp) countProp.textContent = feedData.prop.length;
    if (countExecute) countExecute.textContent = feedData.execute.length;
    if (countShadow) countShadow.textContent = feedData.shadow.length;
    if (countMarketMap) countMarketMap.textContent = feedData.market_map.length;
    
    const metaCount = document.getElementById("market-meta-count");
    if (metaCount) metaCount.textContent = `${feedData.market_map.length} markets scanned`;
}

function getBadgeHtml(displayState, direction) {
    const dir = direction ? direction.toUpperCase() : "NEUTRAL";
    if (displayState === "QUALIFIED") {
        if (dir === "SHORT") {
            return `<span class="badge badge-qualified-short">QUALIFIED SHORT</span>`;
        }
        return `<span class="badge badge-qualified-long">QUALIFIED LONG</span>`;
    } else if (displayState === "WATCH") {
        return `<span class="badge badge-watch">WATCH</span>`;
    } else {
        return `<span class="badge badge-hidden">HIDDEN</span>`;
    }
}

function formatSafeField(val) {
    if (val === null || val === undefined || (typeof val === "string" && val.trim() === "")) {
        return `<span class="not-supplied">Not supplied</span>`;
    }
    return escapeHtml(String(val));
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderDetailsDisclosure(record) {
    const diag = record.diagnostics || {};
    const weReasons = Array.isArray(diag.weighted_eligibility_reason_codes) 
        ? diag.weighted_eligibility_reason_codes.join(", ") 
        : (record.weighted_eligibility_reason_codes ? record.weighted_eligibility_reason_codes.join(", ") : "None");
    
    const legReasons = Array.isArray(diag.legacy_reason_codes) 
        ? diag.legacy_reason_codes.join(", ") 
        : "None";

    return `
        <details class="card-details">
            <summary class="details-summary">Inspect diagnostics</summary>
            <div class="details-body">
                <div><strong>WE Reasons:</strong> ${escapeHtml(weReasons)}</div>
                <div><strong>Legacy Reasons:</strong> ${escapeHtml(legReasons)}</div>
                <div><strong>Anti-Delta State:</strong> ${escapeHtml(record.anti_delta_state || "None")}</div>
                <div><strong>Anti-Delta Reason:</strong> ${escapeHtml(record.anti_delta_reason || "None")}</div>
                <div><strong>Feed Base State:</strong> ${escapeHtml(record.feed_base_state || "N/A")}</div>
                <div><strong>Score Version:</strong> ${escapeHtml(record.score_version || "N/A")}</div>
            </div>
        </details>
    `;
}

// Live Market Pulse (Hero Pulse Panel)
function renderLiveMarketPulse() {
    const container = document.getElementById("live-market-pulse");
    if (!container) return;

    const propList = feedData.prop || [];
    if (!propList.length) {
        container.innerHTML = `
            <div class="card">
                <div class="card-summary">Scanning live market streams. System is applying strict selectivity filters awaiting top-tier qualification threshold crossings.</div>
            </div>
        `;
        return;
    }

    const topCard = propList[0];
    const score = topCard.weighted_eligibility_score ?? "N/A";
    const thresh = topCard.active_weighted_threshold ?? "N/A";
    const pressure = topCard.pressure_strength ?? "N/A";
    const tempo = topCard.absolute_tempo ?? "N/A";
    const deltaState = topCard.delta_state ?? "N/A";
    const antiDeltaState = topCard.anti_delta_state;
    const antiDeltaReason = topCard.anti_delta_reason;

    let antiDeltaHtml = "";
    if (antiDeltaState && antiDeltaState !== "NONE" && antiDeltaState !== "INACTIVE") {
        antiDeltaHtml = `<div class="anti-delta-caution"><strong>Caution (${escapeHtml(antiDeltaState)}):</strong> ${escapeHtml(antiDeltaReason || "Counter-trend pressure noted.")}</div>`;
    }

    container.innerHTML = `
        <div class="card" style="text-align: left;">
            <div class="card-header">
                <span class="card-pair">${escapeHtml(topCard.pair || "UNKNOWN")}</span>
                ${getBadgeHtml(topCard.display_state, topCard.direction)}
            </div>
            <div class="card-metrics">
                <div class="metric-item">
                    <span class="metric-label">Score / Thresh</span>
                    <span class="metric-value">${score} / ${thresh}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">Pressure</span>
                    <span class="metric-value">${pressure}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">Tempo</span>
                    <span class="metric-value">${tempo}</span>
                </div>
            </div>
            <div class="card-summary">
                Momentum conditions meet the current qualification threshold. Delta state: <strong>${escapeHtml(deltaState)}</strong>.
            </div>
            ${antiDeltaHtml}
            ${renderDetailsDisclosure(topCard)}
        </div>
    `;
}

// 1. Opportunities Grid (prop)
function renderPropGrid() {
    const grid = document.getElementById("grid-prop");
    if (!grid) return;

    const items = feedData.prop || [];
    if (!items.length) {
        grid.innerHTML = `<div class="empty-state">No proprietary qualified opportunities currently active.</div>`;
        return;
    }

    grid.innerHTML = items.map(card => {
        const score = card.weighted_eligibility_score ?? "N/A";
        const thresh = card.active_weighted_threshold ?? "N/A";
        const pressure = card.pressure_strength ?? "N/A";
        const tempo = card.absolute_tempo ?? "N/A";
        const deltaState = card.delta_state ?? "N/A";
        const antiDeltaState = card.anti_delta_state;
        const antiDeltaReason = card.anti_delta_reason;

        let antiDeltaHtml = "";
        if (antiDeltaState && antiDeltaState !== "NONE" && antiDeltaState !== "INACTIVE") {
            antiDeltaHtml = `<div class="anti-delta-caution"><strong>Caution:</strong> ${escapeHtml(antiDeltaReason || antiDeltaState)}</div>`;
        }

        return `
            <div class="card">
                <div class="card-header">
                    <span class="card-pair">${escapeHtml(card.pair || "UNKNOWN")}</span>
                    ${getBadgeHtml(card.display_state, card.direction)}
                </div>
                <div class="card-metrics">
                    <div class="metric-item">
                        <span class="metric-label">Score / Thresh</span>
                        <span class="metric-value">${score} / ${thresh}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Pressure</span>
                        <span class="metric-value">${pressure}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Tempo</span>
                        <span class="metric-value">${tempo}</span>
                    </div>
                </div>
                <div class="card-summary">
                    Momentum conditions meet qualification threshold. Delta state: <strong>${escapeHtml(deltaState)}</strong>.
                </div>
                ${antiDeltaHtml}
                ${renderDetailsDisclosure(card)}
            </div>
        `;
    }).join("");
}

// 2. Trade Plan Grid (execute)
function renderExecuteGrid() {
    const grid = document.getElementById("grid-execute");
    if (!grid) return;

    const items = feedData.execute || [];
    if (!items.length) {
        grid.innerHTML = `<div class="empty-state">No actionable trade execution plans available.</div>`;
        return;
    }

    grid.innerHTML = items.map(card => {
        const score = card.weighted_eligibility_score ?? "N/A";

        return `
            <div class="card">
                <div class="card-header">
                    <span class="card-pair">${escapeHtml(card.pair || "UNKNOWN")}</span>
                    ${getBadgeHtml(card.display_state, card.direction)}
                </div>
                <div class="card-metrics">
                    <div class="metric-item" style="grid-column: span 3;">
                        <span class="metric-label">Weighted Eligibility Score</span>
                        <span class="metric-value">${score}</span>
                    </div>
                </div>
                <div class="execution-block">
                    <div class="exec-row">
                        <span class="exec-label">Entry Framework:</span>
                        <span class="exec-value">${formatSafeField(card.entry_framework)}</span>
                    </div>
                    <div class="exec-row">
                        <span class="exec-label">Exit Trigger:</span>
                        <span class="exec-value">${formatSafeField(card.exit_trigger)}</span>
                    </div>
                    <div class="exec-row">
                        <span class="exec-label">Invalidation:</span>
                        <span class="exec-value">${formatSafeField(card.invalidation)}</span>
                    </div>
                </div>
                ${renderDetailsDisclosure(card)}
            </div>
        `;
    }).join("");
}

// 3. Developing Grid (shadow)
function renderShadowGrid() {
    const grid = document.getElementById("grid-shadow");
    if (!grid) return;

    const items = feedData.shadow || [];
    if (!items.length) {
        grid.innerHTML = `<div class="empty-state">No developing candidates currently tracked.</div>`;
        return;
    }

    grid.innerHTML = items.map(card => {
        const score = card.weighted_eligibility_score;
        const thresh = card.active_weighted_threshold;
        let gapText = "N/A";

        if (score !== null && score !== undefined && thresh !== null && thresh !== undefined) {
            const diff = thresh - score;
            gapText = diff >= 0 ? `Gap: ${diff.toFixed(4)}` : `Above threshold`;
        }

        return `
            <div class="card">
                <div class="card-header">
                    <span class="card-pair">${escapeHtml(card.pair || "UNKNOWN")}</span>
                    ${getBadgeHtml(card.display_state, card.direction)}
                </div>
                <div class="card-metrics">
                    <div class="metric-item">
                        <span class="metric-label">Score</span>
                        <span class="metric-value">${score ?? "N/A"}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Threshold</span>
                        <span class="metric-value">${thresh ?? "N/A"}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Proximity</span>
                        <span class="metric-value">${gapText}</span>
                    </div>
                </div>
                <div class="card-summary">
                    Developing candidate monitoring order flow accumulation toward activation boundary.
                </div>
                ${renderDetailsDisclosure(card)}
            </div>
        `;
    }).join("");
}

// 4. Market Map Table (market_map)
function renderMarketMapTable() {
    const tbody = document.getElementById("tbody-market_map");
    if (!tbody) return;

    const items = feedData.market_map || [];
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No market map records available.</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(card => {
        const isHidden = card.display_state === "HIDDEN";
        const rowClass = isHidden ? "row-hidden" : "";
        const score = card.weighted_eligibility_score ?? "N/A";
        const dataAvail = card.data_availability || "live";
        const isStale = dataAvail !== "live" && dataAvail !== "available";

        return `
            <tr class="${rowClass}">
                <td><strong>${escapeHtml(card.pair || "UNKNOWN")}</strong></td>
                <td>${escapeHtml(card.direction || "NEUTRAL")}</td>
                <td>${getBadgeHtml(card.display_state, card.direction)}</td>
                <td>${score}</td>
                <td><span style="color: ${isStale ? 'var(--accent-amber)' : 'var(--accent-emerald);'}">${escapeHtml(dataAvail)}</span></td>
            </tr>
        `;
    }).join("");
}

// Modal management
function openAccessModal() {
    lastFocusedTrigger = document.activeElement;
    const modal = document.getElementById("access-modal");
    if (modal) {
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        const closeBtn = modal.querySelector(".modal-close");
        if (closeBtn) closeBtn.focus();
    }
}

function closeAccessModal() {
    const modal = document.getElementById("access-modal");
    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        if (lastFocusedTrigger) {
            lastFocusedTrigger.focus();
        }
    }
}

function handleRequestAccess() {
    alert("Access request received. Connecting to publisher stream...");
    closeAccessModal();
}

function setupModalListeners() {
    const modal = document.getElementById("access-modal");
    if (!modal) return;

    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal.classList.contains("open")) {
            closeAccessModal();
        }
    });

    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeAccessModal();
        }
    });
}
