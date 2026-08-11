(function () {
  const scriptEditors = [];

  function syncScriptScheduleEditor(editor) {
    const modeSelect = editor.querySelector(".script-schedule-mode-select");
    if (!modeSelect) return;
    const mode = modeSelect.value;
    editor.querySelectorAll("[data-interval-fields]").forEach((node) => {
      node.classList.toggle("d-none", mode !== "interval");
    });
    editor.querySelectorAll("[data-one-off-fields]").forEach((node) => {
      node.classList.toggle("d-none", mode !== "one_off");
    });
    editor.querySelectorAll("[data-manual-fields]").forEach((node) => {
      node.classList.toggle("d-none", mode !== "manual");
    });
    editor.querySelectorAll("[data-scheduled-fields]").forEach((node) => {
      node.classList.toggle("d-none", mode === "manual");
    });
  }

  document.querySelectorAll("[data-script-editor]").forEach((editor) => {
    syncScriptScheduleEditor(editor);
    const modeSelect = editor.querySelector(".script-schedule-mode-select");
    if (modeSelect) {
      modeSelect.addEventListener("change", () => syncScriptScheduleEditor(editor));
    }
  });

  document.querySelectorAll(".script-editor-textarea").forEach((textarea) => {
    textarea.required = false;
    textarea.removeAttribute("required");
    const editor = CodeMirror.fromTextArea(textarea, {
      mode: "shell",
      theme: "material-darker",
      lineNumbers: true,
      lineWrapping: true,
      indentUnit: 2,
      tabSize: 2,
    });
    editor.setSize(null, 340);
    textarea.scriptEditor = editor;
    scriptEditors.push(editor);
    textarea.form?.addEventListener("submit", () => {
      editor.save();
    });
  });

  function parseScriptArgumentPayload(rawValue) {
    try {
      const payload = JSON.parse(rawValue || "{}");
      return {
        positionals: Array.isArray(payload.positionals) ? payload.positionals.filter((item) => item && typeof item === "object") : [],
        flags: Array.isArray(payload.flags) ? payload.flags.filter((item) => item && typeof item === "object") : [],
      };
    } catch (_) {
      return { positionals: [], flags: [] };
    }
  }

  function compactScriptArgumentPayload(payload) {
    return {
      positionals: payload.positionals
        .map((item) => ({ value: String(item.value || "").trim() }))
        .filter((item) => item.value),
      flags: payload.flags
        .map((item) => ({ flag: String(item.flag || "").trim(), value: String(item.value || "").trim() }))
        .filter((item) => item.flag || item.value),
    };
  }

  function getScriptTextForArgumentEditor(editorElement) {
    const scriptTextarea = editorElement.closest("[data-script-editor]")?.querySelector(".script-editor-textarea");
    if (!scriptTextarea) return "";
    return scriptTextarea.scriptEditor ? scriptTextarea.scriptEditor.getValue() : scriptTextarea.value;
  }

  function suggestScriptArguments(scriptText) {
    const suggestions = { positionals: [], flags: [] };
    const positionalIndexes = new Set();
    const positionalPattern = /\$(\d+)|\$\{(\d+)(?::[-=?][^}]*)?\}/g;
    let match;
    while ((match = positionalPattern.exec(scriptText)) !== null) {
      const index = Number(match[1] || match[2] || 0);
      if (index > 0 && index <= 40) positionalIndexes.add(index);
    }
    const maxPositionalIndex = positionalIndexes.size ? Math.max(...positionalIndexes) : 0;
    for (let index = 1; index <= maxPositionalIndex; index += 1) {
      suggestions.positionals.push({ value: "" });
    }

    const flagNames = new Set();
    const caseFlagPattern = /(^|[\s|;&(])(--[A-Za-z0-9][A-Za-z0-9_.:-]*|-[A-Za-z0-9])\)/g;
    while ((match = caseFlagPattern.exec(scriptText)) !== null) {
      flagNames.add(match[2]);
    }
    const getoptsPattern = /getopts\s+["']([A-Za-z0-9:]+)["']/g;
    while ((match = getoptsPattern.exec(scriptText)) !== null) {
      const optString = match[1] || "";
      for (const char of optString.replace(/:/g, "")) {
        flagNames.add(`-${char}`);
      }
    }
    Array.from(flagNames).sort().forEach((flag) => {
      suggestions.flags.push({ flag, value: "" });
    });
    return suggestions;
  }

  function setupScriptArgumentEditor(editorElement) {
    const form = editorElement.closest("form");
    const hiddenInput = form?.querySelector("[data-script-arguments-input]");
    const positionalList = editorElement.querySelector("[data-positional-list]");
    const flagList = editorElement.querySelector("[data-flag-list]");
    const emptyPositionals = editorElement.querySelector("[data-empty-positionals]");
    const emptyFlags = editorElement.querySelector("[data-empty-flags]");
    if (!form || !hiddenInput || !positionalList || !flagList) return;

    let payload = compactScriptArgumentPayload(parseScriptArgumentPayload(hiddenInput.value));

    const syncHidden = () => {
      hiddenInput.value = JSON.stringify(compactScriptArgumentPayload(payload));
      if (emptyPositionals) emptyPositionals.classList.toggle("d-none", payload.positionals.length > 0);
      if (emptyFlags) emptyFlags.classList.toggle("d-none", payload.flags.length > 0);
    };

    const render = () => {
      positionalList.innerHTML = "";
      flagList.innerHTML = "";

      payload.positionals.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "script-argument-row";
        row.innerHTML = `
          <span class="script-argument-index">$${index + 1}</span>
          <input type="text" class="form-control form-control-sm" value="" placeholder="value">
          <button type="button" class="btn btn-outline-danger btn-sm" aria-label="Remove parameter"><i class="bi bi-x-lg"></i></button>
        `;
        const input = row.querySelector("input");
        input.value = item.value || "";
        input.addEventListener("input", () => {
          payload.positionals[index].value = input.value;
          syncHidden();
        });
        row.querySelector("button").addEventListener("click", () => {
          payload.positionals.splice(index, 1);
          render();
        });
        positionalList.appendChild(row);
      });

      payload.flags.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "script-argument-row script-argument-row-flag";
        row.innerHTML = `
          <input type="text" class="form-control form-control-sm script-argument-flag-input" value="" placeholder="-o / --option">
          <input type="text" class="form-control form-control-sm" value="" placeholder="value">
          <button type="button" class="btn btn-outline-danger btn-sm" aria-label="Remove flag"><i class="bi bi-x-lg"></i></button>
        `;
        const inputs = row.querySelectorAll("input");
        inputs[0].value = item.flag || "";
        inputs[1].value = item.value || "";
        inputs[0].addEventListener("input", () => {
          payload.flags[index].flag = inputs[0].value;
          syncHidden();
        });
        inputs[1].addEventListener("input", () => {
          payload.flags[index].value = inputs[1].value;
          syncHidden();
        });
        row.querySelector("button").addEventListener("click", () => {
          payload.flags.splice(index, 1);
          render();
        });
        flagList.appendChild(row);
      });
      syncHidden();
    };

    editorElement.querySelector("[data-add-positional]")?.addEventListener("click", () => {
      payload.positionals.push({ value: "" });
      render();
    });
    editorElement.querySelector("[data-add-flag]")?.addEventListener("click", () => {
      payload.flags.push({ flag: "", value: "" });
      render();
    });
    editorElement.querySelector("[data-suggest-script-arguments]")?.addEventListener("click", () => {
      const suggestions = suggestScriptArguments(getScriptTextForArgumentEditor(editorElement));
      while (payload.positionals.length < suggestions.positionals.length) {
        payload.positionals.push({ value: "" });
      }
      const currentFlags = new Set(payload.flags.map((item) => item.flag).filter(Boolean));
      suggestions.flags.forEach((item) => {
        if (!currentFlags.has(item.flag)) {
          payload.flags.push(item);
          currentFlags.add(item.flag);
        }
      });
      render();
    });
    form.addEventListener("submit", syncHidden);
    render();
  }

  function secondsToEditorState(secondsValue) {
    const seconds = Number(secondsValue || 0);
    if (seconds > 0 && seconds % 60 === 0) return { value: seconds / 60, unit: "minutes" };
    return { value: Math.max(seconds, 1), unit: "seconds" };
  }

  function editorStateToSeconds(value, unit) {
    const amount = Math.max(Number(value || 0), 1);
    if (unit === "hours") return Math.round(amount * 3600);
    if (unit === "minutes") return Math.round(amount * 60);
    return Math.round(amount);
  }

  document.querySelectorAll("[data-script-argument-editor]").forEach(setupScriptArgumentEditor);

  document.querySelectorAll(".modal").forEach((modalElement) => {
    modalElement.addEventListener("shown.bs.modal", () => {
      window.setTimeout(() => {
        scriptEditors.forEach((editor) => editor.refresh());
      }, 0);
    });
  });
  window.setTimeout(() => {
    scriptEditors.forEach((editor) => editor.refresh());
  }, 0);

  document.querySelectorAll("[data-timeout-editor]").forEach((editor) => {
    const hiddenInput = document.getElementById(editor.dataset.timeoutInputId);
    const valueInput = editor.querySelector("[data-timeout-value]");
    const unitSelect = editor.querySelector("[data-timeout-unit]");
    if (!hiddenInput || !valueInput || !unitSelect) return;

    const initial = secondsToEditorState(hiddenInput.value);
    valueInput.value = initial.value;
    unitSelect.value = initial.unit;

    const syncToHidden = () => {
      hiddenInput.value = editorStateToSeconds(valueInput.value, unitSelect.value);
    };

    valueInput.addEventListener("input", syncToHidden);
    unitSelect.addEventListener("change", syncToHidden);
    syncToHidden();
  });

  document.querySelectorAll("[data-script-editor]").forEach((editor) => {
    const scheduleValueInput = editor.querySelector('input[name$="-schedule_minutes"]');
    const scheduleUnitSelect = editor.querySelector('select[name$="-schedule_unit"]');
    if (!scheduleValueInput || !scheduleUnitSelect) return;

    let previousUnit = scheduleUnitSelect.value;
    const syncScheduleValueForUnit = () => {
      const currentValue = Number(scheduleValueInput.value || 0);
      if (scheduleUnitSelect.value === "minutes") {
        if (currentValue < 5) {
          scheduleValueInput.value = 5;
        }
        previousUnit = scheduleUnitSelect.value;
        return;
      }
      if (previousUnit === "minutes" && currentValue >= 5) {
        scheduleValueInput.value = 1;
      }
      previousUnit = scheduleUnitSelect.value;
    };

    scheduleUnitSelect.addEventListener("change", syncScheduleValueForUnit);
  });
})();
