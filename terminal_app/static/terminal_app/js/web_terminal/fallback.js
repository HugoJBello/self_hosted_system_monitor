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
