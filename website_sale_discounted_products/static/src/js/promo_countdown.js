/* Live teller bij de promoties: telt af tot de einddatum van de prijsregel.
   Werkt op elk element .o_promo_countdown[data-end] (UTC-tijd, bv. 2026-10-01T22:00:00Z),
   ook op blokken die pas na het laden van de pagina worden ingevuld. */
(function () {
    "use strict";

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    function format(ms) {
        var total = Math.floor(ms / 1000);
        var days = Math.floor(total / 86400);
        var hours = Math.floor((total % 86400) / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var seconds = total % 60;
        var time = pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
        return days > 0 ? days + "d " + time : time;
    }

    function tick() {
        document.querySelectorAll(".o_promo_countdown[data-end]").forEach(function (el) {
            var left = Date.parse(el.getAttribute("data-end")) - Date.now();
            var value = el.querySelector(".o_promo_countdown_value");
            if (!value || isNaN(left)) {
                return;
            }
            if (left <= 0) {
                el.classList.add("d-none");
                // De actie liep af terwijl de pagina openstond: herlaad de pagina een keer,
                // zodat meteen de prijs van na de actie te zien is (geen F5 nodig).
                if (el.dataset.liep === "1" && !el.dataset.herladen) {
                    el.dataset.herladen = "1";
                    setTimeout(function () {
                        // Niet tijdens het bewerken van de website: dan verlies je je wijzigingen.
                        if (!document.body.classList.contains("editor_enable")) {
                            window.location.reload();
                        }
                    }, 3000);
                }
                return;
            }
            el.dataset.liep = "1";
            el.classList.remove("d-none");
            value.textContent = format(left);
        });
    }

    setInterval(tick, 1000);
    tick();
})();