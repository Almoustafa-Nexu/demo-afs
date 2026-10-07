/**
 * Live teller bij promoties: telt af tot de einddatum van de prijsregel.
 *
 * Werkt op elk element .o_promo_countdown[data-end] (UTC, bv. 2026-10-01T22:00:00Z),
 * ook in blokken die pas na het laden van de pagina gevuld worden.
 */

const pad = (n) => String(n).padStart(2, "0");

function format(ms) {
    const total = Math.floor(ms / 1000);
    const days = Math.floor(total / 86400);
    const time = [
        Math.floor((total % 86400) / 3600),
        Math.floor((total % 3600) / 60),
        total % 60,
    ].map(pad).join(":");
    return days > 0 ? `${days}d ${time}` : time;
}

function tick() {
    for (const el of document.querySelectorAll(".o_promo_countdown[data-end]")) {
        const value = el.querySelector(".o_promo_countdown_value");
        const left = Date.parse(el.dataset.end) - Date.now();
        if (!value || isNaN(left)) {
            continue;
        }
        // Actie voorbij: teller verbergen
        el.classList.toggle("d-none", left <= 0);
        if (left > 0) {
            value.textContent = format(left);
        }
    }
}

setInterval(tick, 1000);
tick();
