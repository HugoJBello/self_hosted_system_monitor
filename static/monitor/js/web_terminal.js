(function () {
  const page = document.querySelector("[data-terminal-page]");
  if (!page || !window.Terminal || !window.FitAddon) return;

  const container = page.querySelector("[data-terminal-container]");
  const stateBadge = page.querySelector("[data-terminal-state]");
  const reconnectButton = page.querySelector("[data-terminal-reconnect]");
  const fitButton = page.querySelector("[data-terminal-fit]");
  const clearButton = page.querySelector("[data-terminal-clear]");
  const mobileKeys = page.querySelector("[data-terminal-mobile-keys]");
  const ctrlToggleButton = page.querySelector("[data-terminal-ctrl-toggle]");
  const fitAddon = new window.FitAddon.FitAddon();
  const webLinksAddon = window.WebLinksAddon ? new window.WebLinksAddon.WebLinksAddon() : null;
  let socket = null;
  let pingTimer = null;
  let resizeTimer = null;
  let fallbackSession = null;
  let fallbackCursor = 0;
  let fallbackPolling = false;
  let fallbackInputQueue = Promise.resolve();
  let websocketGeneration = 0;
  let ctrlArmed = false;
  let terminalSessionId = sessionStorage.getItem(storageKey("session_id")) || "";
  let terminalCursor = 0;
  let reconnectTimer = null;
  let watchdogTimer = null;
  let lastPongAt = 0;
  let lastPingAt = 0;

  const PING_INTERVAL_MS = 30000;
  const PONG_TIMEOUT_MS = 75000;

  const terminal = new window.Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: '"JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace',
    fontSize: window.matchMedia("(max-width: 575px)").matches ? 13 : 14,
    letterSpacing: 0,
    lineHeight: 1.12,
    scrollback: 8000,
    theme: {
      background: "#050a13",
      foreground: "#edf2f7",
      cursor: "#ff7a59",
      selectionBackground: "#335c7a",
      black: "#0b1220",
      red: "#ff7a59",
      green: "#4dd4ac",
      yellow: "#ffd166",
      blue: "#5dc6ff",
      magenta: "#c792ea",
      cyan: "#67d1d5",
      white: "#edf2f7",
      brightBlack: "#64748b",
      brightRed: "#ff9b73",
      brightGreen: "#7ce7c9",
      brightYellow: "#ffe08a",
      brightBlue: "#90d7ff",
      brightMagenta: "#d8a7f4",
      brightCyan: "#9be7eb",
      brightWhite: "#ffffff"
    }
  });

  terminal.loadAddon(fitAddon);
  if (webLinksAddon) terminal.loadAddon(webLinksAddon);
  terminal.open(container);

  function setState(label, level) {
    stateBadge.textContent = label;
    stateBadge.dataset.level = level || "info";
  }

  function websocketUrl() {
    const path = page.dataset.websocketPath || "/ws/terminal/";
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = new URL(path, window.location.origin);
    url.protocol = protocol;
    if (terminalSessionId) url.searchParams.set("session_id", terminalSessionId);
    if (terminalCursor) url.searchParams.set("cursor", String(terminalCursor));
    return url.toString();
  }

  function sendResize() {
    fitAddon.fit();
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "resize", rows: terminal.rows, cols: terminal.cols }));
      return;
    }
    if (fallbackSession) {
      postJson(fallbackSession.resize_url, { rows: terminal.rows, cols: terminal.cols });
    }
  }

  function scheduleResize() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(sendResize, 80);
  }

  function sendTerminalInput(data) {
    if (!data) return;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "input", data }));
      return;
    }
    if (fallbackSession) {
      queueFallbackInput(data);
    }
  }

  function controlCode(letter) {
    const normalized = String(letter || "").toLowerCase();
    if (!/^[a-z]$/.test(normalized)) return "";
    return String.fromCharCode(normalized.charCodeAt(0) - 96);
  }

  function setCtrlArmed(value) {
    ctrlArmed = Boolean(value);
    if (ctrlToggleButton) {
      ctrlToggleButton.setAttribute("aria-pressed", ctrlArmed ? "true" : "false");
      ctrlToggleButton.classList.toggle("is-active", ctrlArmed);
    }
  }

  function mobileKeySequence(key) {
    const sequences = {
      "escape": "\x1b",
      "tab": "\t",
      "arrow-up": "\x1b[A",
      "arrow-down": "\x1b[B",
      "arrow-right": "\x1b[C",
      "arrow-left": "\x1b[D",
      "ctrl-c": "\x03",
      "ctrl-d": "\x04"
    };
    return sequences[key] || "";
  }

  function connect() {
    websocketGeneration += 1;
    const currentGeneration = websocketGeneration;
    if (socket) socket.close();
    stopConnectionTimers();
    window.clearTimeout(reconnectTimer);
    stopFallbackPolling();
    setState(terminalSessionId ? "Restoring" : "Connecting", "info");
    terminal.focus();
    scheduleResize();

    socket = new WebSocket(websocketUrl());
    let opened = false;

    socket.addEventListener("open", () => {
      opened = true;
      lastPongAt = Date.now();
      setState("Connected", "success");
      sendResize();
      startConnectionTimers(currentGeneration);
    });

    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (payload.type === "output") {
        terminal.write(payload.data || "");
        saveCursor(payload.cursor);
      } else if (payload.type === "session") {
        saveSession(payload.session_id, payload.cursor);
        setState(payload.reused ? "Restored" : "Connected", "success");
        sendResize();
      } else if (payload.type === "status") {
        setState(payload.message || "Connected", payload.level || "info");
      } else if (payload.type === "pong") {
        lastPongAt = Date.now();
      }
    });

    socket.addEventListener("close", () => {
      stopConnectionTimers();
      if (currentGeneration !== websocketGeneration) {
        return;
      }
      if (!opened && !fallbackSession) {
        startHttpFallback();
        return;
      }
      setState("Disconnected", "warning");
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      setState("Connection error", "error");
    });
  }

  terminal.onData((data) => {
    if (ctrlArmed) {
      const code = data.length === 1 ? controlCode(data) : "";
      setCtrlArmed(false);
      if (code) {
        sendTerminalInput(code);
        return;
      }
    }
    sendTerminalInput(data);
  });

  window.addEventListener("resize", scheduleResize);
  window.addEventListener("pageshow", restoreAfterPageResume);
  window.addEventListener("online", () => {
    window.setTimeout(forceRestoreIfStale, 1000);
  });
  window.addEventListener("offline", () => {
    setState("Offline", "warning");
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) restoreAfterPageResume();
  });
  if (window.ResizeObserver) {
    new ResizeObserver(scheduleResize).observe(container);
  }

  reconnectButton.addEventListener("click", connect);
  fitButton.addEventListener("click", sendResize);
  clearButton.addEventListener("click", () => terminal.clear());
  if (ctrlToggleButton) {
    ctrlToggleButton.addEventListener("click", () => {
      setCtrlArmed(!ctrlArmed);
      terminal.focus();
    });
  }
  if (mobileKeys) {
    mobileKeys.addEventListener("click", (event) => {
      const button = event.target.closest("[data-terminal-key]");
      if (!button) return;
      sendTerminalInput(mobileKeySequence(button.dataset.terminalKey));
      terminal.focus();
    });
  }

  const mobileViewportQuery = window.matchMedia("(max-width: 768px)");
  const coarsePointerQuery = window.matchMedia("(pointer: coarse)");
  applyMobileKeyboardMode();
  watchMediaQuery(mobileViewportQuery, applyMobileKeyboardMode);
  watchMediaQuery(coarsePointerQuery, applyMobileKeyboardMode);

  connect();

  function applyMobileKeyboardMode() {
    const isMobile = mobileViewportQuery.matches || coarsePointerQuery.matches;
    page.classList.toggle("is-mobile-terminal", isMobile);
    scheduleResize();
  }

  function watchMediaQuery(query, callback) {
    if (query.addEventListener) {
      query.addEventListener("change", callback);
      return;
    }
    if (query.addListener) {
      query.addListener(callback);
    }
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function storageKey(name) {
    return `system-monitor-terminal:${window.location.pathname}:${name}`;
  }

  function parseStoredInteger(value) {
    const parsed = parseInt(value || "0", 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  function saveSession(sessionId, cursor) {
    if (!sessionId) return;
    const previousSessionId = terminalSessionId;
    terminalSessionId = sessionId;
    sessionStorage.setItem(storageKey("session_id"), sessionId);
    if (previousSessionId && previousSessionId !== sessionId) {
      terminal.clear();
    }
    saveCursor(cursor);
  }

  function saveCursor(cursor) {
    const parsed = parseStoredInteger(cursor);
    terminalCursor = parsed;
  }

  function clearStoredSession() {
    terminalSessionId = "";
    terminalCursor = 0;
    sessionStorage.removeItem(storageKey("session_id"));
  }

  function isSocketOpenOrConnecting() {
    return socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING);
  }

  function restoreAfterPageResume() {
    scheduleResize();
    if (!isSocketOpenOrConnecting() && !fallbackPolling) {
      connect();
      return;
    }
    forceRestoreIfStale();
  }

  function scheduleReconnect() {
    if (!terminalSessionId) return;
    window.clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(() => {
      if (!document.hidden && !isSocketOpenOrConnecting()) {
        connect();
      }
    }, 1500);
  }

  function startConnectionTimers(generation) {
    sendPing();
    pingTimer = window.setInterval(sendPing, PING_INTERVAL_MS);
    watchdogTimer = window.setInterval(() => checkConnectionHealth(generation), 5000);
  }

  function stopConnectionTimers() {
    window.clearInterval(pingTimer);
    window.clearInterval(watchdogTimer);
    pingTimer = null;
    watchdogTimer = null;
  }

  function sendPing() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    lastPingAt = Date.now();
    socket.send(JSON.stringify({ type: "ping" }));
  }

  function checkConnectionHealth(generation) {
    if (generation !== websocketGeneration || document.hidden || !terminalSessionId) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (Date.now() - lastPongAt < PONG_TIMEOUT_MS) return;
    setState("Restoring", "warning");
    connect();
  }

  function forceRestoreIfStale() {
    if (!terminalSessionId || fallbackPolling) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      connect();
      return;
    }
    if (lastPingAt && Date.now() - lastPongAt >= PONG_TIMEOUT_MS) {
      setState("Restoring", "warning");
      connect();
    }
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken()
      },
      body: JSON.stringify(payload || {})
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  async function startHttpFallback() {
    if (fallbackSession) return;
    setState("HTTP fallback", "warning");
    try {
      fitAddon.fit();
      fallbackSession = await postJson(page.dataset.terminalApiStartUrl, {
        rows: terminal.rows,
        cols: terminal.cols,
        session_id: terminalSessionId
      });
      fallbackCursor = fallbackSession.reused ? terminalCursor : 0;
      saveSession(fallbackSession.session_id, fallbackCursor);
      fallbackPolling = true;
      fallbackInputQueue = Promise.resolve();
      pollFallback();
    } catch (error) {
      setState("Disconnected", "error");
    }
  }

  async function pollFallback() {
    while (fallbackPolling && fallbackSession) {
      try {
        const separator = fallbackSession.poll_url.includes("?") ? "&" : "?";
        const response = await fetch(`${fallbackSession.poll_url}${separator}cursor=${fallbackCursor}`, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        fallbackCursor = payload.cursor || fallbackCursor;
        saveCursor(fallbackCursor);
        if (payload.output) terminal.write(payload.output);
        if (!payload.alive) {
          setState(payload.reason || "Disconnected", "warning");
          fallbackPolling = false;
          fallbackSession = null;
          clearStoredSession();
        }
      } catch (error) {
        setState("Disconnected", "error");
        fallbackPolling = false;
        fallbackSession = null;
        scheduleReconnect();
      }
    }
  }

  function stopFallbackPolling() {
    if (!fallbackSession) return;
    fallbackPolling = false;
    fallbackSession = null;
    fallbackInputQueue = Promise.resolve();
  }

  function closeFallback() {
    if (!fallbackSession) return;
    const closeUrl = fallbackSession.close_url;
    stopFallbackPolling();
    clearStoredSession();
    postJson(closeUrl, {}).catch(() => {});
  }

  function queueFallbackInput(data) {
    fallbackInputQueue = fallbackInputQueue
      .then(() => {
        if (!fallbackSession) return null;
        return postJson(fallbackSession.input_url, { data });
      })
      .catch(() => {
        setState("Input error", "error");
      });
  }
})();
