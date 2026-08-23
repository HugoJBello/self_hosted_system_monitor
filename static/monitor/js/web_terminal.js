(function () {
  const page = document.querySelector("[data-terminal-page]");
  if (!page || !window.Terminal || !window.FitAddon) return;

  const container = page.querySelector("[data-terminal-container]");
  const stateBadge = page.querySelector("[data-terminal-state]");
  const reconnectButton = page.querySelector("[data-terminal-reconnect]");
  const newSessionButton = page.querySelector("[data-terminal-new-session]");
  const fitButton = page.querySelector("[data-terminal-fit]");
  const clearButton = page.querySelector("[data-terminal-clear]");
  const mobileKeys = page.querySelector("[data-terminal-mobile-keys]");
  const ctrlToggleButton = page.querySelector("[data-terminal-ctrl-toggle]");
  const fitAddon = new window.FitAddon.FitAddon();
  const webLinksAddon = window.WebLinksAddon ? new window.WebLinksAddon.WebLinksAddon() : null;
  const mobileInput = document.createElement("textarea");
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
  let replayedBlankRestore = false;
  let socketReadyForInput = false;
  let mobileKeyboardMode = false;
  let mobileInputValue = "";
  let mobileViewportScrollTimer = null;
  let restoreMobileScrollTimer = null;
  const pendingInputQueue = [];

  const PING_INTERVAL_MS = 30000;
  const PONG_TIMEOUT_MS = 75000;
  const PENDING_INPUT_TTL_MS = 5000;
  const MAX_PENDING_INPUT_CHARS = 4096;

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
  setupMobileInputBridge();
  configureHelperTextarea();

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
    if (terminalCursor && !shouldReplayFromStart()) url.searchParams.set("cursor", String(terminalCursor));
    return url.toString();
  }

  function sessionCloseUrl(sessionId) {
    const template = page.dataset.terminalApiCloseUrlTemplate || "";
    if (!template || !sessionId) return "";
    return template.replace("__session_id__", encodeURIComponent(sessionId));
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
    if (socketReadyForInput && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "input", data }));
      return;
    }
    if (fallbackSession) {
      queueFallbackInput(data);
      return;
    }
    if (isSocketOpenOrConnecting() || terminalSessionId) {
      queuePendingInput(data);
      if (!isSocketOpenOrConnecting()) connect();
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
    socketReadyForInput = false;
    stopConnectionTimers();
    window.clearTimeout(reconnectTimer);
    stopFallbackPolling();
    setState(terminalSessionId ? "Restoring" : "Connecting", "info");
    focusTerminal();
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
        replayedBlankRestore = false;
        refreshTerminal();
      } else if (payload.type === "session") {
        saveSession(payload.session_id, payload.cursor);
        setState(payload.reused ? "Restored" : "Connected", "success");
        socketReadyForInput = true;
        flushPendingInput(payload);
        sendResize();
        window.setTimeout(refreshTerminal, 0);
      } else if (payload.type === "status") {
        setState(payload.message || "Connected", payload.level || "info");
      } else if (payload.type === "pong") {
        lastPongAt = Date.now();
      }
    });

    socket.addEventListener("close", () => {
      stopConnectionTimers();
      socketReadyForInput = false;
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

  terminal.onData(sendInteractiveInput);

  function sendInteractiveInput(data) {
    if (ctrlArmed) {
      const code = data.length === 1 ? controlCode(data) : "";
      setCtrlArmed(false);
      if (code) {
        sendTerminalInput(code);
        return true;
      }
    }
    sendTerminalInput(data);
    return false;
  }

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
  if (newSessionButton) {
    newSessionButton.addEventListener("click", forceNewTerminal);
  }
  fitButton.addEventListener("click", sendResize);
  clearButton.addEventListener("click", () => terminal.clear());
  if (ctrlToggleButton) {
    ctrlToggleButton.addEventListener("click", () => {
      setCtrlArmed(!ctrlArmed);
      focusTerminal();
    });
  }
  if (mobileKeys) {
    mobileKeys.addEventListener("click", (event) => {
      const button = event.target.closest("[data-terminal-key]");
      if (!button) return;
      sendTerminalInput(mobileKeySequence(button.dataset.terminalKey));
      if (button.dataset.terminalKey !== "tab") resetMobileInputValue();
      focusTerminal();
    });
  }
  container.addEventListener("pointerdown", focusTerminal);
  container.addEventListener("touchstart", focusTerminal, { passive: true });
  container.addEventListener("click", focusTerminal);
  document.addEventListener("selectionchange", () => {
    if (mobileKeyboardMode) return;
    if (document.activeElement && container.contains(document.activeElement)) {
      focusTerminal();
    }
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scheduleResize);
    window.visualViewport.addEventListener("scroll", scheduleResize);
    window.visualViewport.addEventListener("resize", scheduleMobileViewportAlignment);
  }

  const mobileViewportQuery = window.matchMedia("(max-width: 768px)");
  const coarsePointerQuery = window.matchMedia("(pointer: coarse)");
  const touchCapableDevice = Boolean(navigator.maxTouchPoints || navigator.msMaxTouchPoints);
  applyMobileKeyboardMode();
  watchMediaQuery(mobileViewportQuery, applyMobileKeyboardMode);
  watchMediaQuery(coarsePointerQuery, applyMobileKeyboardMode);

  connect();

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
    socketReadyForInput = false;
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
      flushPendingInput({ session_id: fallbackSession.session_id, reused: fallbackSession.reused });
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
        if (payload.output) {
          terminal.write(payload.output);
          replayedBlankRestore = false;
          refreshTerminal();
        }
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

  async function closeCurrentSession(sessionId) {
    const closeUrl = fallbackSession?.close_url || sessionCloseUrl(sessionId);
    if (!closeUrl) return;
    await postJson(closeUrl, {});
  }

  async function forceNewTerminal() {
    const sessionId = terminalSessionId;
    websocketGeneration += 1;
    pendingInputQueue.length = 0;
    resetMobileInputValue();
    setCtrlArmed(false);
    socketReadyForInput = false;
    window.clearTimeout(reconnectTimer);
    stopConnectionTimers();
    stopFallbackPolling();
    clearStoredSession();
    terminal.clear();
    setState("Starting new terminal", "info");

    if (socket) {
      socket.close();
      socket = null;
    }

    try {
      await closeCurrentSession(sessionId);
    } catch (error) {
    }

    connect();
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

  function queuePendingInput(data) {
    const now = Date.now();
    pendingInputQueue.push({
      data,
      sessionId: terminalSessionId || "",
      createdAt: now
    });
    trimPendingInput(now);
  }

  function trimPendingInput(now) {
    while (pendingInputQueue.length && now - pendingInputQueue[0].createdAt > PENDING_INPUT_TTL_MS) {
      pendingInputQueue.shift();
    }

    let totalChars = pendingInputQueue.reduce((total, item) => total + item.data.length, 0);
    while (pendingInputQueue.length && totalChars > MAX_PENDING_INPUT_CHARS) {
      const removed = pendingInputQueue.shift();
      totalChars -= removed ? removed.data.length : 0;
    }
  }

  function flushPendingInput(sessionPayload) {
    if (!pendingInputQueue.length) return;
    const now = Date.now();
    trimPendingInput(now);

    const activeSessionId = sessionPayload.session_id || terminalSessionId || "";
    const sessionWasReused = Boolean(sessionPayload.reused);
    const flushable = [];

    pendingInputQueue.forEach((item) => {
      const queuedBeforeKnownSession = !item.sessionId;
      const queuedForSameSession = sessionWasReused && item.sessionId === activeSessionId;
      if (queuedBeforeKnownSession || queuedForSameSession) {
        flushable.push(item.data);
      }
    });

    pendingInputQueue.length = 0;
    if (!flushable.length) return;

    sendTerminalInput(flushable.join(""));
  }

  function focusTerminal() {
    if (mobileKeyboardMode) {
      focusMobileInput();
      return;
    }
    terminal.focus();
    const helper = container.querySelector(".xterm-helper-textarea");
    configureHelperTextarea(helper);
    if (helper && document.activeElement !== helper) {
      try {
        helper.focus({ preventScroll: true });
      } catch (error) {
        helper.focus();
      }
    }
  }

  function configureHelperTextarea(helperElement) {
    const helper = helperElement || container.querySelector(".xterm-helper-textarea");
    if (!helper) return;
    helper.setAttribute("inputmode", "text");
    helper.setAttribute("enterkeyhint", "enter");
    helper.setAttribute("autocomplete", "off");
    helper.setAttribute("autocapitalize", "none");
    helper.setAttribute("autocorrect", "off");
    helper.setAttribute("spellcheck", "false");
  }

  function setupMobileInputBridge() {
    mobileInput.className = "terminal-mobile-input";
    mobileInput.setAttribute("aria-label", "Terminal keyboard input");
    mobileInput.setAttribute("inputmode", "text");
    mobileInput.setAttribute("enterkeyhint", "enter");
    mobileInput.setAttribute("autocomplete", "off");
    mobileInput.setAttribute("autocapitalize", "none");
    mobileInput.setAttribute("autocorrect", "off");
    mobileInput.setAttribute("spellcheck", "false");
    mobileInput.rows = 1;
    mobileInput.value = "";
    mobileInput.style.cssText = [
      "position:fixed",
      "top:0",
      "left:0",
      "width:1px",
      "height:1px",
      "min-width:1px",
      "min-height:1px",
      "padding:0",
      "border:0",
      "outline:0",
      "opacity:0",
      "color:transparent",
      "background:transparent",
      "caret-color:transparent",
      "resize:none",
      "overflow:hidden",
      "pointer-events:none",
      "z-index:0"
    ].join(";");
    document.body.appendChild(mobileInput);

    mobileInput.addEventListener("keydown", handleMobileInputKeydown);
    mobileInput.addEventListener("input", handleMobileInput);
    mobileInput.addEventListener("compositionend", () => {
      window.setTimeout(handleMobileInput, 0);
    });
  }

  function focusMobileInput() {
    configureHelperTextarea();
    positionMobileInputAnchor();
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    if (document.activeElement !== mobileInput) {
      try {
        mobileInput.focus({ preventScroll: true });
      } catch (error) {
        mobileInput.focus();
      }
    }
    keepMobileInputCaretAtEnd();
    restoreWindowScroll(scrollX, scrollY);
  }

  function handleMobileInputKeydown(event) {
    if (!mobileKeyboardMode) return;
    if (event.key === "Enter") {
      event.preventDefault();
      sendTerminalInput("\r");
      resetMobileInputValue();
      stabilizeMobileInputViewport();
      return;
    }
    if (event.key === "Backspace" && !mobileInput.value) {
      event.preventDefault();
      sendTerminalInput("\x7f");
      resetMobileInputValue();
      stabilizeMobileInputViewport();
      return;
    }
    if (event.key === "Delete") {
      event.preventDefault();
      sendTerminalInput("\x1b[3~");
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      sendTerminalInput("\x1b");
      resetMobileInputValue();
    }
  }

  function handleMobileInput() {
    if (!mobileKeyboardMode) return;
    const nextValue = mobileInput.value || "";
    const sequence = inputDiffToTerminalSequence(mobileInputValue, nextValue);
    mobileInputValue = nextValue;
    const consumedControl = sequence ? sendInteractiveInput(sequence) : false;
    if (consumedControl) resetMobileInputValue();
    keepMobileInputCaretAtEnd();
    stabilizeMobileInputViewport();
  }

  function inputDiffToTerminalSequence(previousValue, nextValue) {
    if (previousValue === nextValue) return "";
    let prefixLength = 0;
    const maxPrefix = Math.min(previousValue.length, nextValue.length);
    while (prefixLength < maxPrefix && previousValue[prefixLength] === nextValue[prefixLength]) {
      prefixLength += 1;
    }

    let suffixLength = 0;
    const maxSuffix = Math.min(previousValue.length - prefixLength, nextValue.length - prefixLength);
    while (
      suffixLength < maxSuffix &&
      previousValue[previousValue.length - 1 - suffixLength] === nextValue[nextValue.length - 1 - suffixLength]
    ) {
      suffixLength += 1;
    }

    const removedCount = previousValue.length - prefixLength - suffixLength;
    const insertedText = nextValue.slice(prefixLength, nextValue.length - suffixLength);
    return "\x7f".repeat(Math.max(0, removedCount)) + insertedText.replace(/\n/g, "\r");
  }

  function keepMobileInputCaretAtEnd() {
    const end = mobileInput.value.length;
    try {
      mobileInput.setSelectionRange(end, end);
    } catch (error) {
    }
  }

  function resetMobileInputValue() {
    mobileInputValue = "";
    mobileInput.value = "";
  }

  function stabilizeMobileInputViewport() {
    if (!mobileKeyboardMode) return;
    positionMobileInputAnchor();
    window.requestAnimationFrame(() => {
      try {
        terminal.refresh(0, Math.max(0, terminal.rows - 1));
      } catch (error) {
      }
    });
  }

  function scheduleMobileViewportAlignment() {
    window.clearTimeout(mobileViewportScrollTimer);
    mobileViewportScrollTimer = window.setTimeout(() => {
      positionMobileInputAnchor();
    }, 120);
  }

  function positionMobileInputAnchor() {
    if (!mobileInput || !container) return;
    const viewport = currentVisualViewport();
    const cursorRect = visibleCursorRect();
    const containerRect = container.getBoundingClientRect();
    const fallbackTop = Math.max(containerRect.top + 12, viewport.top + 8);
    const fallbackLeft = Math.max(containerRect.left + 12, viewport.left + 8);
    const top = clamp((cursorRect ? cursorRect.top : fallbackTop), viewport.top + 8, viewport.bottom - 32);
    const left = clamp((cursorRect ? cursorRect.left : fallbackLeft), viewport.left + 8, viewport.right - 32);
    mobileInput.style.top = `${Math.max(0, top)}px`;
    mobileInput.style.left = `${Math.max(0, left)}px`;
  }

  function visibleCursorRect() {
    const cursor = container.querySelector(".xterm-cursor");
    if (!cursor) return null;
    const rect = cursor.getBoundingClientRect();
    if (!rect.width && !rect.height) return null;
    const viewport = currentVisualViewport();
    const visible = rect.bottom >= viewport.top && rect.top <= viewport.bottom && rect.right >= viewport.left && rect.left <= viewport.right;
    return visible ? rect : null;
  }

  function currentVisualViewport() {
    const viewport = window.visualViewport;
    const left = viewport ? viewport.offsetLeft : 0;
    const top = viewport ? viewport.offsetTop : 0;
    const width = viewport ? viewport.width : window.innerWidth;
    const height = viewport ? viewport.height : window.innerHeight;
    return {
      left,
      top,
      right: left + width,
      bottom: top + height
    };
  }

  function restoreWindowScroll(scrollX, scrollY) {
    window.clearTimeout(restoreMobileScrollTimer);
    const restore = () => {
      if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
        window.scrollTo(scrollX, scrollY);
      }
    };
    restore();
    restoreMobileScrollTimer = window.setTimeout(restore, 0);
  }

  function clamp(value, min, max) {
    if (max < min) return min;
    return Math.min(Math.max(value, min), max);
  }

  function refreshTerminal() {
    try {
      fitAddon.fit();
      terminal.refresh(0, Math.max(0, terminal.rows - 1));
    } catch (error) {
    }
  }

  function terminalLooksBlank() {
    const buffer = terminal.buffer && terminal.buffer.active;
    if (!buffer) return false;
    const visibleRows = Math.max(1, terminal.rows || 1);
    for (let index = 0; index < visibleRows; index += 1) {
      const line = buffer.getLine(index);
      if (line && line.translateToString(true).trim()) {
        return false;
      }
    }
    return true;
  }

  function shouldReplayFromStart() {
    if (!terminalSessionId || !terminalCursor || replayedBlankRestore || !terminalLooksBlank()) {
      return false;
    }
    replayedBlankRestore = true;
    return true;
  }
})();
