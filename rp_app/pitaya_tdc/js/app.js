(function () {
    "use strict";

    var APP_ID = "pitaya_tdc";
    var API_PATHS = ["/pitaya_tdc/api", "http://" + location.hostname + ":8080/api"];
    var apiBase = API_PATHS[0];
    var POLL_MS = 100;
    var BAD_FLAGS = { unmatched_stop: 1, timeout: 1, overflow: 1 };

    var lastSeq = null;
    var lastGood = null;
    var lastGoodAt = 0;
    var seqWindow = [];
    var started = false;

    function $(id) {
        return document.getElementById(id);
    }

    function fmtNs(dt) {
        if (dt === null || dt === undefined) {
            return "—";
        }
        var v = Number(dt);
        if (!isFinite(v)) {
            return String(dt);
        }
        var av = Math.abs(v);
        if (av >= 1e6) {
            return (v / 1e6).toFixed(3) + " ms";
        }
        if (av >= 1e3) {
            return (v / 1e3).toFixed(3) + " µs";
        }
        return v.toFixed(1) + " ns";
    }

    function isGoodPair(latest) {
        if (!latest || !latest.valid) {
            return false;
        }
        var flags = latest.flags || [];
        for (var i = 0; i < flags.length; i++) {
            if (BAD_FLAGS[flags[i]]) {
                return false;
            }
        }
        return true;
    }

    function meaning(flags, valid, armed) {
        flags = flags || [];
        if (!valid) {
            return "No completed pair yet. Waiting for START, then STOP.";
        }
        if (flags.indexOf("unmatched_stop") >= 0) {
            return "STOP rose while idle (no START first). Not a delay.";
        }
        if (flags.indexOf("timeout") >= 0) {
            return "START seen, STOP never arrived (timeout).";
        }
        if (flags.indexOf("overflow") >= 0) {
            return "Wait counter wrapped. Interval too long.";
        }
        if (armed) {
            return "Good last pair. Currently armed — waiting for STOP.";
        }
        return "Good START→STOP pair.";
    }

    function pad(n) {
        return (n < 10 ? "0" : "") + n;
    }

    function stamp() {
        var d = new Date();
        return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    }

    function getJson(path) {
        return fetch(apiBase + path, { cache: "no-store" }).then(function (res) {
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        });
    }

    function getJsonAny(path) {
        return getJson(path).catch(function () {
            var next = API_PATHS[0] === apiBase ? API_PATHS[1] : API_PATHS[0];
            apiBase = next;
            return getJson(path);
        });
    }

    function startApp() {
        return fetch("/bazaar?start=" + encodeURIComponent(APP_ID), { cache: "no-store" })
            .then(function (res) {
                return res.text().then(function (body) {
                    started = true;
                    return body;
                });
            })
            .catch(function () {
                started = true;
            });
    }

    function connectWs() {
        var urls = [
            "ws://" + location.hostname + ":9002",
            (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/wss",
        ];
        var i = 0;
        function tryNext() {
            if (i >= urls.length) {
                return;
            }
            var ws;
            try {
                ws = new WebSocket(urls[i++]);
            } catch (e) {
                tryNext();
                return;
            }
            ws.onerror = function () {
                try {
                    ws.close();
                } catch (e2) { /* ignore */ }
                tryNext();
            };
        }
        tryNext();
    }

    function apply(err, health, latest) {
        if (err) {
            $("status").textContent = "Waiting for TDC server…";
            $("health").textContent = "offline";
            $("meaning").textContent = "FPGA and tdc_server.py start when this app opens.";
            return;
        }

        var ok = !!(health && health.ok);
        $("health").textContent =
            "id=" + ((health && health.id) || "?") +
            "  enable=" + (health ? health.enable : "?") +
            "  mmcm=" + (health ? health.mmcm_locked : "?");
        $("status").textContent = ok ? "Connected" : "FPGA ID mismatch — is tdc.bin loaded?";

        latest = latest || {};
        var valid = !!latest.valid;
        var seq = latest.seq;
        var flags = latest.flags || [];
        var armed = !!latest.armed;
        var good = isGoodPair(latest);
        var now = Date.now() / 1000;
        var validOnly = $("validOnly").checked;

        if (good) {
            lastGood = latest;
            lastGoodAt = now;
        }

        var show = latest;
        if (validOnly && !good) {
            show = lastGood;
        }
        var shownValid = !!(show && show.valid);
        var shownFlags = (show && show.flags) || [];
        var shownSeq = show ? show.seq : null;
        var dtNs = shownValid && show ? show.dt_ns : null;

        $("dt").textContent = shownValid ? fmtNs(dtNs) : "—";
        $("seq").textContent = shownSeq !== null && shownSeq !== undefined ? String(shownSeq) : "—";
        $("flags").textContent = shownFlags.length ? shownFlags.join(", ") : "(none)";
        $("armed").textContent = armed ? "yes — waiting for STOP" : "no";

        var age = show ? show.age_ms : null;
        if (show === lastGood && show !== latest) {
            age = (now - lastGoodAt) * 1000;
        }
        $("age").textContent = typeof age === "number" ? age.toFixed(1) + " ms" : "—";

        if (validOnly && !good) {
            $("meaning").textContent = lastGood
                ? "Holding last valid pair. Latest FPGA result was not a delay."
                : "Waiting for a valid START→STOP pair.";
        } else {
            $("meaning").textContent = meaning(flags, valid, armed);
        }

        if (seq !== null && seq !== undefined) {
            if (!validOnly || good) {
                seqWindow.push([now, Number(seq)]);
            }
            var cutoff = now - 1;
            seqWindow = seqWindow.filter(function (p) { return p[0] >= cutoff; });
            if (seqWindow.length >= 2) {
                var dt = seqWindow[seqWindow.length - 1][0] - seqWindow[0][0];
                var hz = 0;
                if (dt > 0) {
                    if (validOnly) {
                        hz = (seqWindow.length - 1) / dt;
                    } else {
                        hz = (seqWindow[seqWindow.length - 1][1] - seqWindow[0][1]) / dt;
                    }
                }
                $("rate").textContent = hz >= 1 ? hz.toFixed(0) + " events/s" : hz.toFixed(2) + " events/s";
            } else {
                $("rate").textContent = "—";
            }

            if (lastSeq !== null && seq !== lastSeq) {
                if (!validOnly || good) {
                    var line =
                        stamp() +
                        "  seq=" + seq +
                        "  " + fmtNs(valid ? latest.dt_ns : null) +
                        "  flags=" + (flags.length ? flags.join(",") : "-") +
                        "  armed=" + armed +
                        "\n";
                    var log = $("log");
                    log.textContent += line;
                    if (log.textContent.length > 40000) {
                        log.textContent = log.textContent.slice(-30000);
                    }
                    log.scrollTop = log.scrollHeight;
                }
            }
            lastSeq = seq;
        }
    }

    function poll() {
        Promise.all([getJsonAny("/health"), getJsonAny("/latest")])
            .then(function (pair) {
                apply(null, pair[0], pair[1]);
            })
            .catch(function (err) {
                apply(String(err), null, null);
            });
    }

    startApp().then(function () {
        connectWs();
        poll();
        setInterval(poll, POLL_MS);
    });
})();
