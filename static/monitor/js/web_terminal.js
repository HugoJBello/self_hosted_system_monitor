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
    return `${protocol}://${window.location.host}${path}`;
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
    window.clearInterval(pingTimer);
    closeFallback();
    setState("Connecting", "info");
    terminal.focus();
    scheduleResize();

    socket = new WebSocket(websocketUrl());
    let opened = false;

    socket.addEventListener("open", () => {
      opened = true;
      setState("Connected", "success");
      sendResize();
      pingTimer = window.setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, 30000);
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
      } else if (payload.type === "status") {
        setState(payload.message || "Connected", payload.level || "info");
      }
    });

    socket.addEventListener("close", () => {
      window.clearInterval(pingTimer);
      if (currentGeneration !== websocketGeneration) {
        return;
      }
      if (!opened && !fallbackSession) {
        startHttpFallback();
        return;
      }
      setState("Disconnected", "warning");
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
      fallbackSession = await postJson(page.dataset.terminalApiStartUrl, { rows: terminal.rows, cols: terminal.cols });
      fallbackCursor = 0;
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
        if (payload.output) terminal.write(payload.output);
        if (!payload.alive) {
          setState(payload.reason || "Disconnected", "warning");
          fallbackPolling = false;
          fallbackSession = null;
        }
      } catch (error) {
        setState("Disconnected", "error");
        fallbackPolling = false;
        fallbackSession = null;
      }
    }
  }

  function closeFallback() {
    if (!fallbackSession) return;
    const closeUrl = fallbackSession.close_url;
    fallbackPolling = false;
    fallbackSession = null;
    fallbackInputQueue = Promise.resolve();
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
