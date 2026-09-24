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
