  function applyMobileKeyboardMode() {
    const isMobile = touchCapableDevice && (mobileViewportQuery.matches || coarsePointerQuery.matches);
    mobileKeyboardMode = isMobile;
    page.classList.toggle("is-mobile-terminal", isMobile);
    container.classList.toggle("uses-mobile-input-bridge", isMobile);
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
      replayedBlankRestore = false;
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
    focusTerminal();
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
