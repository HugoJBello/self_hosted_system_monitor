(function () {
  function fieldValue(editor, suffix) {
    const field = editor.querySelector(`[name$="${suffix}"]`);
    return field ? field.value.trim() : "";
  }

  function checkedValue(editor, suffix) {
    const field = editor.querySelector(`[name$="${suffix}"]`);
    return field ? field.checked : false;
  }

  function setText(editor, selector, value) {
    editor.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
    });
  }

  function setHtmlList(node, items) {
    if (!node) return;
    node.innerHTML = "";
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      node.appendChild(li);
    });
  }

  function backupTypeState(editor) {
    const type = fieldValue(editor, "backup_type") || "remote";
    const remoteDirection = fieldValue(editor, "remote_direction") || "push";
    const httpDirection = fieldValue(editor, "http_direction") || "push";
    const localSource = fieldValue(editor, "source_path") || "Local folder not set";
    const localDestination = fieldValue(editor, "local_dest_path") || "Local destination not set";
    const remoteHost = fieldValue(editor, "remote_host") || "remote host not set";
    const remoteUser = fieldValue(editor, "remote_user");
    const remoteDir = fieldValue(editor, "remote_dir") || "remote directory not set";
    const httpUrl = fieldValue(editor, "http_remote_url") || "HTTP server not set";
    const httpPath = fieldValue(editor, "http_remote_path") || "remote folder not set";
    const deleteEnabled = checkedValue(editor, "delete_enabled");
    const remoteLabel = `${remoteUser ? `${remoteUser}@` : ""}${remoteHost}:${remoteDir}`;
    const httpLabel = `${httpUrl.replace(/\/$/, "")}:${httpPath}`;

    if (type === "local") {
      return {
        title: "Local memory backup",
        summary: "Copies a local folder to another local folder on this host.",
        shortSummary: "Local folder copied to a local destination.",
        direction: "Local origin -> local destination",
        origin: localSource,
        destination: localDestination,
        risk: deleteEnabled
          ? "The local destination is updated and files missing from the origin can be deleted there."
          : "The local destination is updated. Existing files with the same paths can be overwritten.",
        requirements: ["A readable local source folder.", "A writable local destination folder.", "Use mount verification for removable USB or mounted destinations."],
        localSourceLabel: "Local source folder",
        localSourceHelp: "Origin. Files are read from this local folder.",
        localDestinationLabel: "Local destination folder",
        localDestinationHelp: "Destination. Files can be created, updated, overwritten, and, when delete is enabled, deleted here.",
        remoteDirLabel: "Remote directory",
        remoteDirHelp: "",
        httpRemotePathLabel: "Remote folder",
        httpRemotePathHelp: "",
      };
    }
    if (type === "http") {
      const pull = httpDirection === "pull";
      return {
        title: "HTTP server to server backup",
        summary: pull
          ? "Pulls files from a remote System Monitor HTTP backup endpoint into a local destination."
          : "Pushes local files to a remote System Monitor HTTP backup endpoint.",
        shortSummary: pull ? "Remote HTTP folder copied into a local destination." : "Local folder copied to a remote HTTP server.",
        direction: pull ? "Remote HTTP origin -> local destination" : "Local origin -> remote HTTP destination",
        origin: pull ? httpLabel : localSource,
        destination: pull ? localDestination : httpLabel,
        risk: pull
          ? (deleteEnabled ? "The local destination is updated and files missing from the remote origin can be deleted locally." : "The local destination is updated. Existing local files with the same paths can be overwritten.")
          : (deleteEnabled ? "The remote HTTP folder is updated and files missing locally can be deleted on the remote server." : "The remote HTTP folder is updated. Existing remote files with the same paths can be overwritten."),
        requirements: ["The remote server must run this same project.", "The remote server must expose the HTTP backup endpoints.", "The Bearer token must match the token configured in Settings on the remote server."],
        localSourceLabel: pull ? "Local folder" : "Local source folder",
        localSourceHelp: pull ? "Not used for HTTP pull. The local destination field below receives the files." : "Origin. Files are read from this local folder and uploaded to the remote HTTP server.",
        localDestinationLabel: "Local destination folder",
        localDestinationHelp: pull ? "Destination. Files can be created, updated, overwritten, and, when delete is enabled, deleted here." : "Not used for HTTP push.",
        remoteDirLabel: "Remote directory",
        remoteDirHelp: "",
        httpRemotePathLabel: pull ? "Remote source folder" : "Remote destination folder",
        httpRemotePathHelp: pull ? "Origin on the remote HTTP server. The local destination is made to match this folder." : "Destination on the remote HTTP server. It is updated from the local source.",
      };
    }
    const pull = remoteDirection === "pull";
    return {
      title: "SSH + rsync backup",
      summary: pull ? "Runs rsync over SSH from the remote directory into a local folder." : "Runs rsync over SSH from a local folder into the remote directory.",
      shortSummary: pull ? "Remote SSH directory copied into a local folder." : "Local folder copied to a remote SSH directory.",
      direction: pull ? "Remote SSH origin -> local destination" : "Local origin -> remote SSH destination",
      origin: pull ? remoteLabel : localSource,
      destination: pull ? localSource : remoteLabel,
      risk: pull
        ? (deleteEnabled ? "The local folder is the destination and files missing from the remote origin can be deleted locally." : "The local folder is the destination. Existing local files with the same paths can be overwritten.")
        : (deleteEnabled ? "The remote directory is the destination and files missing locally can be deleted remotely." : "The remote directory is the destination. Existing remote files with the same paths can be overwritten."),
      requirements: ["SSH connectivity to the remote host.", "Valid SSH user and authentication.", "rsync available for the SSH copy path.", "Cloudflare fields only when Connection mode uses Cloudflare Access and direct SSH is not enough."],
      localSourceLabel: pull ? "Local destination folder" : "Local source folder",
      localSourceHelp: pull ? "Destination. Remote files are copied into this local folder; it can be overwritten and, with delete enabled, cleaned." : "Origin. Files are read from this local folder and sent to the remote SSH directory.",
      localDestinationLabel: "Local destination folder",
      localDestinationHelp: "Not used for SSH jobs. SSH pull uses the local folder field above as the destination.",
      remoteDirLabel: pull ? "Remote source directory" : "Remote destination directory",
      remoteDirHelp: pull ? "Origin on the remote SSH host. The local destination is made to match this directory." : "Destination on the remote SSH host. It is updated from the local source.",
      httpRemotePathLabel: "Remote folder",
      httpRemotePathHelp: "",
    };
  }

  function updateBackupInfoModal(editor) {
    const state = backupTypeState(editor);
    const modal = document.getElementById("backupTypeInfoModal");
    if (!modal) return;
    modal.querySelector("[data-backup-type-info-title]").textContent = state.title;
    modal.querySelector("[data-backup-type-info-summary]").textContent = state.summary;
    modal.querySelector("[data-backup-type-info-direction]").textContent = state.direction;
    modal.querySelector("[data-backup-type-info-origin]").textContent = state.origin;
    modal.querySelector("[data-backup-type-info-destination]").textContent = state.destination;
    modal.querySelector("[data-backup-type-info-risk]").textContent = state.risk;
    setHtmlList(modal.querySelector("[data-backup-type-info-requirements]"), state.requirements);
  }

  function syncBackupEditor(editor) {
    const typeSelect = editor.querySelector(".backup-type-select");
    const connectionModeSelect = editor.querySelector(".backup-connection-mode-select");
    const httpDirectionSelect = editor.querySelector(".backup-http-direction-select");
    const remoteDirectionSelect = editor.querySelector('[name$="remote_direction"]');
    const scheduleModeSelect = editor.querySelector(".backup-schedule-mode-select");
    const isLocal = typeSelect && typeSelect.value === "local";
    const isHttp = typeSelect && typeSelect.value === "http";
    const isHttpPull = isHttp && httpDirectionSelect && httpDirectionSelect.value === "pull";
    const isRemote = !isLocal && !isHttp;
    const isCloudflare = isRemote && connectionModeSelect && connectionModeSelect.value === "cloudflare";
    const isManual = scheduleModeSelect && scheduleModeSelect.value === "manual";
    editor.querySelectorAll("[data-local-fields]").forEach((node) => {
      node.classList.toggle("d-none", !isLocal);
    });
    editor.querySelectorAll("[data-local-source-fields]").forEach((node) => {
      node.classList.toggle("d-none", isHttpPull);
    });
    editor.querySelectorAll("[data-local-destination-fields]").forEach((node) => {
      node.classList.toggle("d-none", !(isLocal || isHttpPull));
    });
    editor.querySelectorAll("[data-remote-fields]").forEach((node) => {
      node.classList.toggle("d-none", !isRemote);
    });
    editor.querySelectorAll("[data-cloudflare-fields]").forEach((node) => {
      node.classList.toggle("d-none", !isCloudflare);
    });
    editor.querySelectorAll("[data-http-fields]").forEach((node) => {
      node.classList.toggle("d-none", !isHttp);
    });
    editor.querySelectorAll("[data-backup-interval-fields], [data-backup-scheduled-fields]").forEach((node) => {
      node.classList.toggle("d-none", isManual);
    });
    editor.querySelectorAll("[data-backup-manual-fields]").forEach((node) => {
      node.classList.toggle("d-none", !isManual);
    });
    const state = backupTypeState(editor);
    setText(editor, "[data-delete-help]", state.risk);
    setText(editor, "[data-backup-type-summary]", state.shortSummary);
    setText(editor, "[data-local-source-label]", state.localSourceLabel);
    setText(editor, "[data-local-source-help]", state.localSourceHelp);
    setText(editor, "[data-local-destination-label]", state.localDestinationLabel);
    setText(editor, "[data-local-destination-help]", state.localDestinationHelp);
    setText(editor, "[data-remote-dir-label]", state.remoteDirLabel);
    setText(editor, "[data-remote-dir-help]", state.remoteDirHelp);
    setText(editor, "[data-http-remote-path-label]", state.httpRemotePathLabel);
    setText(editor, "[data-http-remote-path-help]", state.httpRemotePathHelp);
    setText(editor, "[data-copy-plan-title]", state.direction);
    setText(editor, "[data-copy-origin]", state.origin);
    setText(editor, "[data-copy-destination]", state.destination);
    setText(editor, "[data-copy-risk]", state.risk);

    editor.querySelectorAll("[data-max-size-enabled]").forEach((toggle) => {
      const maxSizeInput = editor.querySelector("[data-max-size-input]");
      if (!maxSizeInput) return;
      maxSizeInput.disabled = !toggle.checked;
      maxSizeInput.classList.toggle("disabled", !toggle.checked);
    });
  }

  let backupInfoReturnModal = null;
  const infoModalElement = document.getElementById("backupTypeInfoModal");
  if (infoModalElement) {
    infoModalElement.addEventListener("hidden.bs.modal", () => {
      if (backupInfoReturnModal) {
        bootstrap.Modal.getOrCreateInstance(backupInfoReturnModal).show();
        backupInfoReturnModal = null;
      }
    });
  }

  document.querySelectorAll("[data-backup-editor]").forEach((editor) => {
    syncBackupEditor(editor);
    ["change", "input"].forEach((eventName) => {
      editor.querySelectorAll("input, textarea, select").forEach((field) => {
        field.addEventListener(eventName, () => syncBackupEditor(editor));
      });
    });
    editor.querySelectorAll("[data-backup-type-info-button]").forEach((button) => {
      button.addEventListener("click", () => {
        updateBackupInfoModal(editor);
        const parentModal = button.closest(".modal");
        if (parentModal && infoModalElement) {
          backupInfoReturnModal = parentModal;
          infoModalElement.addEventListener("shown.bs.modal", () => {
            bootstrap.Modal.getOrCreateInstance(parentModal).hide();
          }, { once: true });
        }
      });
    });
  });

  function secondsToEditorState(secondsValue) {
    const seconds = Number(secondsValue || 0);
    if (seconds > 0 && seconds % 60 === 0) {
      return { value: seconds / 60, unit: "minutes" };
    }
    return { value: Math.max(seconds, 1), unit: "seconds" };
  }

  function editorStateToSeconds(value, unit) {
    const amount = Math.max(Number(value || 0), 1);
    if (unit === "hours") return Math.round(amount * 3600);
    if (unit === "minutes") return Math.round(amount * 60);
    return Math.round(amount);
  }

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
})();
