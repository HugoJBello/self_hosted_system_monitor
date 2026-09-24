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
