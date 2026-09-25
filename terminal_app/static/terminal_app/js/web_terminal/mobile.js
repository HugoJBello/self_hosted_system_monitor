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

  function scheduleTerminalRefresh({ scrollToBottom = false } = {}) {
    const refresh = () => {
      if (!container.isConnected) return;
      refreshTerminal();
      if (scrollToBottom) {
        try {
          terminal.scrollToBottom();
        } catch (error) {
        }
      }
    };

    refresh();
    [80, 240, 700].forEach((delay) => window.setTimeout(refresh, delay));
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
