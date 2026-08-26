(function () {
    "use strict";

    var APP_ID = "pitaya_tdc";
    var API_PATHS = ["/pitaya_tdc/api", "http://" + location.hostname + ":8080/api"];
    var CONTROL = "/pitaya_tdc/control";
    var apiBase = API_PATHS[0];
    var POLL_MS = 100;
    var CONTROL_POLL_MS = 1000;
    var BAD_FLAGS = { unmatched_stop: 1, timeout: 1, overflow: 1 };

    var lastSeq = null;
    var lastGood = null;
    var lastGoodAt = 0;
    var seqWindow = [];
    var started = false;
    var tdcRunning = false;
    var controlBusy = false;
    var stopping = false;
    var starting = false;
    var startError = null;
    var startSince = 0;

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

    function latestFlags(latest) {
        if (!latest) {
            return [];
        }
        if (Object.prototype.hasOwnProperty.call(latest, "latest_flags")) {
            return latest.latest_flags || [];
        }
        return latest.flags || [];
    }

    function fpgaSeqOf(latest) {
        if (!latest) {
            return null;
        }
        if (latest.fpga_seq !== undefined && latest.fpga_seq !== null) {
            return Number(latest.fpga_seq);
        }
        if (latest.seq !== undefined && latest.seq !== null) {
            return Number(latest.seq);
        }
        return null;
    }

    function hasBadFlag(flags) {
        flags = flags || [];
        for (var i = 0; i < flags.length; i++) {
            if (BAD_FLAGS[flags[i]]) {
                return true;
            }
        }
        return false;
    }

    function isRawGood(latest) {
        if (!latest || latest.held) {
            return false;
        }
        if (!latest.valid) {
            return false;
        }
        return !hasBadFlag(latestFlags(latest));
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

    function meaningSameBin(latest) {
        if (!latest || latest.held || !latest.same_bin) {
            return null;
        }
        if (Number(latest.dt_ns) !== 0) {
            return null;
        }
        return "START and STOP in the same 4 ns bin (true 0 ns, or crosstalk).";
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

    var fillingPins = false;
    var pinsLoaded = false;
    var pinsLoading = false;

    function fillPinSelect(sel, pins, current) {
        sel.innerHTML = "";
        for (var i = 0; i < pins.length; i++) {
            var p = pins[i];
            var opt = document.createElement("option");
            opt.value = String(p.index);
            opt.textContent = p.label || (p.name + " (E1 pin " + p.e1 + ")");
            if (p.index === current) {
                opt.selected = true;
            }
            sel.appendChild(opt);
        }
    }

    function applyPinUi(payload) {
        var row = $("pinRow");
        var startSel = $("startPin");
        var stopSel = $("stopPin");
        row.style.display = "";
        var list = (payload && payload.pins) || [];
        if (!list.length) {
            return;
        }
        fillingPins = true;
        fillPinSelect(startSel, list, payload.start && payload.start.index);
        fillPinSelect(stopSel, list, payload.stop && payload.stop.index);
        fillingPins = false;
        var selectable = !!(payload && payload.selectable);
        startSel.disabled = !selectable || !tdcRunning;
        stopSel.disabled = !selectable || !tdcRunning;
        pinsLoaded = selectable || list.length > 0;
        var s = payload.start && payload.start.label;
        var t = payload.stop && payload.stop.label;
        if (!selectable) {
            $("wiring").textContent =
                (payload && payload.error) ||
                "Pin mux not in this bitstream. Rebuild tdc.bit and reinstall. Default is still DIO7_P (E1 pin 17) / DIO7_N (E1 pin 18).";
        } else if (s && t) {
            $("wiring").textContent =
                "START = " + s + ", STOP = " + t +
                " (3.3 V TTL rising edge). Stop restores Scope; leaving this page does not.";
        }
    }

    function putPins() {
        var start = Number($("startPin").value);
        var stop = Number($("stopPin").value);
        if (start === stop) {
            $("meaning").textContent = "START and STOP must be different pins.";
            return;
        }
        fetch(apiBase + "/pins", {
            method: "PUT",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start: start, stop: stop }),
        })
            .then(function (res) {
                return res.json().then(function (body) {
                    if (!res.ok) {
                        throw new Error(body.error || ("HTTP " + res.status));
                    }
                    return body;
                });
            })
            .then(function (payload) {
                lastGood = null;
                lastGoodAt = 0;
                applyPinUi(payload);
            })
            .catch(function (err) {
                $("meaning").textContent = String(err.message || err);
            });
    }

    function loadPins() {
        if (pinsLoading) {
            return;
        }
        pinsLoading = true;
        getJsonAny("/pins")
            .then(function (payload) {
                pinsLoading = false;
                applyPinUi(payload);
            })
            .catch(function () {
                pinsLoading = false;
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

    function setButtons(running, busy) {
        $("btnStart").disabled = !!(busy || running);
        $("btnStop").disabled = !(running || starting);
    }

    function applyStopped(status) {
        tdcRunning = false;
        if (!controlBusy) {
            setButtons(false, false);
        }
        $("status").textContent = "Stopped — Start to load TDC";
        $("health").textContent = (status && status.fpga_id && status.fpga_id !== "TDC1")
            ? ("stopped  fpga=" + status.fpga_id)
            : "stopped";
        $("meaning").textContent = startError
            ? startError
            : "Press Start to load the TDC FPGA and poll server. Leaving this page does nothing.";
        $("dt").textContent = "—";
        $("startPin").disabled = true;
        $("stopPin").disabled = true;
        pinsLoaded = false;
    }

    function postControl(cmd) {
        controlBusy = true;
        setButtons(tdcRunning, true);
        $("status").textContent = cmd === "start" ? "Starting…" : "Stopping…";
        var opts = { method: "POST", cache: "no-store" };
        var timer = null;
        if (typeof AbortController !== "undefined") {
            var ac = new AbortController();
            opts.signal = ac.signal;
            timer = setTimeout(function () {
                ac.abort();
            }, cmd === "start" ? 8000 : 8000);
        }
        return fetch(CONTROL + "/" + cmd, opts)
            .then(function (res) {
                return res.text().then(function (text) {
                    var body = {};
                    try {
                        body = text ? JSON.parse(text) : {};
                    } catch (e) {
                        throw new Error(text ? text.slice(0, 180) : ("HTTP " + res.status));
                    }
                    if (!res.ok) {
                        throw new Error(body.error || ("HTTP " + res.status));
                    }
                    return body;
                });
            })
            .catch(function (err) {
                if (err && err.name === "AbortError") {
                    throw new Error(cmd === "start"
                        ? "Start timed out — FPGA overlay may still be finishing. Try again in a few seconds."
                        : "Stop timed out");
                }
                throw err;
            })
            .finally(function () {
                if (timer) {
                    clearTimeout(timer);
                }
                controlBusy = false;
            });
    }

    function apply(err, health, latest) {
        if (err) {
            $("status").textContent = "TDC server not responding";
            $("health").textContent = "offline";
            $("meaning").textContent = "FPGA may still be loading. If this stays, check /tmp/pitaya_tdc.log.";
            return;
        }

        var ok = !!(health && health.ok);
        $("health").textContent =
            "id=" + ((health && health.id) || "?") +
            "  enable=" + (health ? health.enable : "?") +
            "  mmcm=" + (health ? health.mmcm_locked : "?");
        $("status").textContent = ok ? "Connected" : "FPGA ID mismatch — is tdc.bin loaded?";
        if (ok && !pinsLoaded) {
            loadPins();
        }

        latest = latest || {};
        var valid = !!latest.valid;
        var seq = latest.seq;
        var flags = latestFlags(latest);
        var armed = !!latest.armed;
        var rawGood = isRawGood(latest);
        var now = Date.now() / 1000;
        var validOnly = $("validOnly").checked;
        var fpgaSeq = fpgaSeqOf(latest);

        if ((rawGood || (latest.held && latest.valid)) && Number(latest.dt_ns) !== 0) {
            lastGood = latest;
            lastGoodAt = now;
        }

        var show = latest;
        if (validOnly && !rawGood && !latest.held) {
            show = lastGood;
        }
        var shownValid = !!(show && show.valid);
        var shownFlags = show ? latestFlags(show) : [];
        if (show === latest) {
            shownFlags = flags;
        }
        var shownSeq = show ? show.seq : null;
        var dtNs = shownValid && show ? show.dt_ns : null;

        $("dt").textContent = shownValid ? fmtNs(dtNs) : "—";
        $("seq").textContent = shownSeq !== null && shownSeq !== undefined ? String(shownSeq) : "—";
        $("fpgaSeq").textContent = fpgaSeq !== null && !isNaN(fpgaSeq) ? String(fpgaSeq) : "—";
        $("flags").textContent = shownFlags.length ? shownFlags.join(", ") : "(none)";
        $("latestFlags").textContent = flags.length ? flags.join(", ") : "(none)";
        $("held").textContent = latest.held ? "yes" : "no";
        $("sameBin").textContent = (show && show.same_bin) ? "yes" : "no";
        var t0 = show ? show.t_start_ticks : null;
        var t1 = show ? show.t_stop_ticks : null;
        $("tStart").textContent = t0 !== undefined && t0 !== null ? String(t0) : "—";
        $("tStop").textContent = t1 !== undefined && t1 !== null ? String(t1) : "—";
        $("armed").textContent = armed ? "yes — waiting for STOP" : "no";

        var age = show ? show.age_ms : null;
        if (show === lastGood && show !== latest) {
            age = (now - lastGoodAt) * 1000;
        }
        $("age").textContent = typeof age === "number" ? age.toFixed(1) + " ms" : "—";

        var sameBinMsg = meaningSameBin(show === latest ? latest : show);
        if (sameBinMsg) {
            $("meaning").textContent = sameBinMsg;
        } else if (latest.held || (validOnly && !rawGood)) {
            $("meaning").textContent = (lastGood || latest.held)
                ? "Holding last valid pair. Latest FPGA result was not a delay."
                : "Waiting for a valid START→STOP pair.";
        } else {
            $("meaning").textContent = meaning(flags, valid, armed);
        }

        if (fpgaSeq !== null) {
            seqWindow.push([now, fpgaSeq]);
            var cutoff = now - 1;
            seqWindow = seqWindow.filter(function (p) { return p[0] >= cutoff; });
            if (seqWindow.length >= 2) {
                var dt = seqWindow[seqWindow.length - 1][0] - seqWindow[0][0];
                var hz = 0;
                if (dt > 0) {
                    hz = (seqWindow[seqWindow.length - 1][1] - seqWindow[0][1]) / dt;
                }
                $("rate").textContent = hz >= 1 ? hz.toFixed(0) + " events/s" : hz.toFixed(2) + " events/s";
            } else {
                $("rate").textContent = "—";
            }

            if (lastSeq !== null && fpgaSeq !== lastSeq) {
                if (!validOnly || rawGood) {
                    var line =
                        stamp() +
                        "  seq=" + (seq !== null && seq !== undefined ? seq : fpgaSeq) +
                        "  " + fmtNs(shownValid ? dtNs : null) +
                        "  flags=" + (flags.length ? flags.join(",") : "-") +
                        "  latest=" + (flags.length ? flags.join(",") : "-") +
                        "  held=" + !!latest.held +
                        "  same_bin=" + !!latest.same_bin +
                        "  t=" + (latest.t_start_ticks != null ? latest.t_start_ticks : "-") +
                        ".." + (latest.t_stop_ticks != null ? latest.t_stop_ticks : "-") +
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
            lastSeq = fpgaSeq;
        }
    }

    function pollData() {
        if (!tdcRunning) {
            return;
        }
        Promise.all([getJsonAny("/health"), getJsonAny("/latest")])
            .then(function (pair) {
                apply(null, pair[0], pair[1]);
            })
            .catch(function () {
                $("status").textContent = "TDC server not responding";
            });
    }

    function poll() {
        fetch(CONTROL + "/status", { cache: "no-store" })
            .then(function (res) {
                if (!res.ok) {
                    throw new Error("HTTP " + res.status);
                }
                return res.json();
            })
            .then(function (st) {
                var running = !!(st && st.state === "running");
                var isStarting = !!(st && st.state === "starting") || starting;
                if (stopping) {
                    if (!running) {
                        applyStopped(st);
                    }
                    return null;
                }
                if (running) {
                    starting = false;
                    startSince = 0;
                    startError = null;
                    controlBusy = false;
                    tdcRunning = true;
                    setButtons(true, false);
                    pollData();
                    return null;
                }
                tdcRunning = false;
                if (isStarting) {
                    starting = true;
                    if (!startSince) {
                        startSince = Date.now();
                    }
                    if (Date.now() - startSince > 40000) {
                        startError = "Start is taking too long. Try Stop, then Start again.";
                        $("status").textContent = "Starting… stuck";
                        $("meaning").textContent = startError;
                        setButtons(false, false);
                        $("btnStop").disabled = false;
                        return null;
                    }
                    $("status").textContent = "Starting…";
                    setButtons(true, true);
                    return null;
                }
                starting = false;
                startSince = 0;
                if (!controlBusy) {
                    setButtons(false, false);
                    applyStopped(st);
                }
                return null;
            })
            .catch(function (err) {
                if (controlBusy) {
                    return;
                }
                $("status").textContent = "Waiting for control helper…";
                $("health").textContent = "offline";
                $("meaning").textContent = String(err.message || err);
                setButtons(false, false);
                $("startPin").disabled = true;
                $("stopPin").disabled = true;
            });
    }

    startApp().then(function () {
        connectWs();
        $("startPin").addEventListener("change", function () {
            if (!fillingPins) {
                putPins();
            }
        });
        $("stopPin").addEventListener("change", function () {
            if (!fillingPins) {
                putPins();
            }
        });
        $("btnStart").addEventListener("click", function () {
            starting = true;
            startSince = Date.now();
            stopping = false;
            startError = null;
            $("status").textContent = "Starting…";
            postControl("start")
                .then(function (body) {
                    if (body && body.state === "running") {
                        starting = false;
                    }
                    pinsLoaded = false;
                    poll();
                })
                .catch(function (err) {
                    starting = false;
                    startError = String(err.message || err);
                    $("meaning").textContent = startError;
                    poll();
                });
        });
        $("btnStop").addEventListener("click", function () {
            stopping = true;
            tdcRunning = false;
            applyStopped();
            $("status").textContent = "Stopping…";
            postControl("stop")
                .then(function () {
                    stopping = false;
                    applyStopped();
                    poll();
                })
                .catch(function (err) {
                    stopping = false;
                    $("meaning").textContent = String(err.message || err);
                    poll();
                });
        });
        applyStopped();
        poll();
        setInterval(poll, CONTROL_POLL_MS);
        setInterval(pollData, POLL_MS);
    });
})();
