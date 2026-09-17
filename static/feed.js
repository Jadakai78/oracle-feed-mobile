(() => {
  "use strict";

  const API_URL = "/api/feed";

  const byId = (id) => document.getElementById(id);

  function firstExistingId(ids) {
    for (const id of ids) {
      const element = byId(id);
      if (element) {
        return element;
      }
    }
    return null;
  }

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }
    return String(value);
  }

  function escapeHtml(value) {
    return text(value, "").replace(/[&<>"']/g, (character) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      };
      return entities[character];
    });
  }

  function cardsMarkup(records, emptyMessage) {
    if (!Array.isArray(records) || records.length === 0) {
      return `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    }

    return records.map((record) => {
      const blockers = Array.isArray(record.eligibility_blockers)
        ? record.eligibility_blockers
        : [];

      const blockerText = blockers.length
        ? blockers.join(" · ")
        : "No active blockers";

      const geometry = [
        record.entry_display,
        record.stop_loss_display,
        record.take_profit_display,
        record.take_profit_2_display,
        record.risk_reward_display,
      ].filter(Boolean).join(" • ");

      return `
        <article class="signal-card ${escapeHtml(record.display_state || "HIDDEN").toLowerCase()}">
          <div class="signal-card-header">
            <div>
              <h3>${escapeHtml(record.pair)}</h3>
              <p>${escapeHtml(record.direction)} · ${escapeHtml(record.display_state)}</p>
            </div>
            <div class="score-badge">${escapeHtml(record.confidence)}</div>
          </div>

          <div class="signal-grid">
            <div>
              <span>Eligibility</span>
              <strong>${escapeHtml(record.eligibility_state)}</strong>
            </div>
            <div>
              <span>Gate</span>
              <strong>${escapeHtml(record.weighted_core_gate)}</strong>
            </div>
            <div>
              <span>HTF</span>
              <strong>${escapeHtml(record.higher_timeframe_direction)}</strong>
            </div>
            <div>
              <span>Source</span>
              <strong>${escapeHtml(record.source)}</strong>
            </div>
          </div>

          <p class="geometry-line">${escapeHtml(geometry || "No entry geometry published")}</p>
          <p class="blocker-line">${escapeHtml(blockerText)}</p>
        </article>
      `;
    }).join("");
  }

  function setText(ids, value) {
    const element = firstExistingId(ids);
    if (element) {
      element.textContent = text(value);
    }
  }

  function setHtml(ids, value) {
    const element = firstExistingId(ids);
    if (element) {
      element.innerHTML = value;
    }
  }

  function renderFeed(payload) {
    const tabs = payload.tabs || {};

    const qualified = Array.isArray(payload.qualified)
      ? payload.qualified
      : (Array.isArray(tabs.qualified) ? tabs.qualified : []);

    const watch = Array.isArray(payload.watch)
      ? payload.watch
      : (Array.isArray(tabs.watch) ? tabs.watch : []);

    const hidden = Array.isArray(payload.hidden)
      ? payload.hidden
      : (Array.isArray(tabs.hidden) ? tabs.hidden : []);

    setText(
      ["qualified-count", "qualifiedCount", "count-qualified"],
      qualified.length
    );

    setText(
      ["watch-count", "watchCount", "count-watch"],
      watch.length
    );

    setText(
      ["hidden-count", "hiddenCount", "count-hidden"],
      hidden.length
    );

    setText(
      ["feed-status", "feedStatus", "status"],
      payload.source && payload.source.status
        ? payload.source.status
        : "LIVE_SNAPSHOT"
    );

    setText(
      ["feed-generated-at", "generatedAt", "last-updated"],
      payload.source && payload.source.file_generated_at
        ? payload.source.file_generated_at
        : payload.generated_at_utc
    );

    setHtml(
      ["qualified-list", "qualifiedList", "qualified-cards"],
      cardsMarkup(
        qualified,
        "No execution-eligible sale-feed records in this snapshot."
      )
    );

    setHtml(
      ["watch-list", "watchList", "watch-cards"],
      cardsMarkup(
        watch,
        "No watch-state sale-feed records in this snapshot."
      )
    );

    setHtml(
      ["hidden-list", "hiddenList", "hidden-cards", "all-list"],
      cardsMarkup(
        hidden,
        "No hidden or rejected records in this snapshot."
      )
    );

    const errorBox = firstExistingId([
      "feed-error",
      "feedError",
      "api-error",
    ]);

    if (errorBox) {
      errorBox.textContent = "";
      errorBox.hidden = true;
    }
  }

  function renderError(error) {
    const message = `Failed to load feed data from API: ${error.message}`;

    const errorBox = firstExistingId([
      "feed-error",
      "feedError",
      "api-error",
    ]);

    if (errorBox) {
      errorBox.textContent = message;
      errorBox.hidden = false;
      return;
    }

    const main = document.querySelector("main") || document.body;
    const existing = document.querySelector(".feed-api-error");

    if (existing) {
      existing.textContent = message;
      return;
    }

    const element = document.createElement("div");
    element.className = "feed-api-error";
    element.textContent = message;
    main.prepend(element);
  }

  async function loadFeed() {
    const response = await fetch(API_URL, {
      cache: "no-store",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();

    if (!payload || typeof payload !== "object") {
      throw new Error("Invalid JSON payload");
    }

    renderFeed(payload);
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadFeed().catch(renderError);
  });
})();