  function openDestinationModal(action) {
    if (!selectedPaths.size) return;
    destinationAction = ["move", "compress", "uncompress"].includes(action) ? action : "copy";
    if (fileActionInput) fileActionInput.value = "";
    if (conflictPolicy) conflictPolicy.value = "overwrite";
    if (folderConflictPolicy) folderConflictPolicy.value = "merge";
    if (transferMethod) transferMethod.value = "standard";
    if (rsyncDelete) rsyncDelete.checked = false;
    if (compressionMethod) compressionMethod.value = "deflated";
    if (compressArchiveName) compressArchiveName.value = defaultArchiveName();
    setCompressStatus("", false);
    resetDestinationNewFolder();
    destinationPlanConfirmed = false;
    showDestinationPicker();
    if (destinationSubmit) destinationSubmit.value = destinationAction;
    if (destinationTitle) {
      destinationTitle.textContent = destinationActionTitle();
    }
    window.history.pushState({ fileManagerDestinationPath: currentPath || "/" }, "", window.location.href);
    loadDestination(currentPath || "/", { updateHistory: false });
    if (window.bootstrap && destinationModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(destinationModalElement).show();
    }
  }

  function destinationUsesSingleClickOpen() {
    return hasSingleClickOpenPreference ? singleClickOpenEnabled : true;
  }

  function showDestinationPicker() {
    destinationPlanConfirmed = false;
    destinationPickerUi?.classList.remove("d-none");
    destinationPlan?.classList.add("d-none");
    if (destinationSubmit) {
      destinationSubmit.textContent = `Review ${destinationActionVerb()} plan`;
    }
    destinationPlanEdit?.classList.add("d-none");
    updateDestinationActionUi();
    updateRsyncOptions();
  }

  function updateDestinationActionUi() {
    const compressing = destinationAction === "compress";
    const uncompressing = destinationAction === "uncompress";
    compressOptions?.classList.toggle("d-none", !compressing);
    transferMethodPanel?.classList.toggle("d-none", compressing || uncompressing);
    rsyncOptions?.classList.toggle("d-none", true);
    conflictPolicies?.classList.toggle("d-none", false);
    folderConflictPolicyPanel?.classList.toggle("d-none", compressing);
    if (conflictPolicyLabel) {
      conflictPolicyLabel.textContent = compressing ? "Archive conflicts" : uncompressing ? "Extracted file conflicts" : "File conflicts";
    }
    updateConflictOptionLabels(compressing, uncompressing);
  }

  function updateConflictOptionLabels(compressing, uncompressing = false) {
    if (!conflictPolicy) return;
    const labels = compressing
      ? {
          overwrite: "Overwrite existing archive",
          skip: "Skip if archive exists",
          rename: "Rename archive (1), (2)...",
        }
      : uncompressing
      ? {
          overwrite: "Overwrite existing extracted files",
          skip: "Skip existing extracted files",
          rename: "Rename extracted files (1), (2)...",
        }
      : {
          overwrite: "Overwrite existing file",
          skip: "Skip existing file",
          rename: "Rename incoming file (1), (2)...",
        };
    Array.from(conflictPolicy.options).forEach((option) => {
      if (labels[option.value]) option.textContent = labels[option.value];
    });
  }

  function destinationActionTitle() {
    if (destinationAction === "move") return "Move selected items";
    if (destinationAction === "compress") return "Compress selected items";
    if (destinationAction === "uncompress") return "Uncompress archive";
    return "Copy selected items";
  }

  function destinationActionVerb() {
    if (destinationAction === "move") return "move";
    if (destinationAction === "compress") return "compression";
    if (destinationAction === "uncompress") return "extraction";
    return "copy";
  }

  function setDestinationNewFolderEnabled(enabled, { focus = false } = {}) {
    destinationNewFolderEnabled = Boolean(enabled);
    destinationNewFolderFields?.classList.toggle("d-none", !destinationNewFolderEnabled);
    destinationNewFolderToggle?.setAttribute("aria-expanded", destinationNewFolderEnabled ? "true" : "false");
    if (!destinationNewFolderEnabled && destinationNewFolderName) {
      destinationNewFolderName.value = "";
    }
    setDestinationNewFolderStatus("", false);
    if (destinationNewFolderInput) destinationNewFolderInput.value = normalizedDestinationNewFolderName();
    destinationPlanConfirmed = false;
    if (destinationNewFolderEnabled && focus) {
      window.setTimeout(() => destinationNewFolderName?.focus(), 0);
    }
  }

  function resetDestinationNewFolder() {
    if (destinationNewFolderName) destinationNewFolderName.value = "";
    setDestinationNewFolderEnabled(false);
  }

  function normalizedDestinationNewFolderName() {
    return destinationNewFolderEnabled ? (destinationNewFolderName?.value || "").trim() : "";
  }

  function validateDestinationNewFolder() {
    const folderName = normalizedDestinationNewFolderName();
    if (!destinationNewFolderEnabled) return true;
    if (!folderName) {
      setDestinationNewFolderStatus("Folder name is required.", true);
      destinationNewFolderName?.focus();
      return false;
    }
    if (folderName === "." || folderName === ".." || /[\\/]/.test(folderName) || /[\n\r\0]/.test(folderName)) {
      setDestinationNewFolderStatus("Folder name cannot contain path separators or line breaks.", true);
      destinationNewFolderName?.focus();
      return false;
    }
    setDestinationNewFolderStatus("", false);
    return true;
  }

  function setDestinationNewFolderStatus(message, isError) {
    if (!destinationNewFolderStatus) return;
    destinationNewFolderStatus.textContent = message || "";
    destinationNewFolderStatus.classList.toggle("d-none", !message);
    destinationNewFolderStatus.classList.toggle("is-error", Boolean(isError));
  }

  function updateRsyncOptions() {
    if (destinationAction === "compress" || destinationAction === "uncompress") {
      rsyncOptions?.classList.add("d-none");
      if (rsyncDelete) rsyncDelete.checked = false;
      rsyncDeleteWarning?.classList.add("d-none");
      return;
    }
    const isRsync = transferMethod?.value === "rsync";
    const items = selectedItems();
    const foldersOnly = items.length > 0 && items.every((item) => item.kind === "folder");
    const compatiblePolicies = conflictPolicy?.value === "overwrite" && folderConflictPolicy?.value === "merge";
    const canDelete = isRsync && foldersOnly && compatiblePolicies;
    rsyncOptions?.classList.toggle("d-none", !isRsync);
    if (rsyncDelete) {
      rsyncDelete.disabled = !canDelete;
      if (!canDelete) rsyncDelete.checked = false;
    }
    rsyncDeleteWarning?.classList.toggle("d-none", !Boolean(rsyncDelete?.checked));
  }

  function showDestinationPlan() {
    const items = selectedItems();
    if (!items.length || !destinationPath) return;
    if (!validateDestinationNewFolder()) return;
    if (!validateCompressOptions()) return;
    updateRsyncOptions();
    const isRsync = transferMethod?.value === "rsync";
    if (isRsync && rsyncDelete?.disabled && rsyncDelete?.checked) {
      return;
    }
    if (destinationPickerUi) destinationPickerUi.classList.add("d-none");
    if (destinationPlan) destinationPlan.classList.remove("d-none");
    if (destinationSubmit) {
      destinationSubmit.textContent = destinationAction === "move" ? "Confirm move" : destinationAction === "compress" ? "Confirm compress" : destinationAction === "uncompress" ? "Confirm extract" : "Confirm copy";
    }
    if (fileActionInput) fileActionInput.value = destinationAction;
    if (destinationPathInput) destinationPathInput.value = destinationPath;
    if (destinationNewFolderInput) destinationNewFolderInput.value = normalizedDestinationNewFolderName();
    syncSelectedInputs();
    destinationPlanEdit?.classList.remove("d-none");
    if (destinationPlanMethod) {
      destinationPlanMethod.textContent = transferMethod?.selectedOptions?.[0]?.textContent?.trim() || "Standard";
    }
    renderDestinationPlanItems(items);
    renderDestinationPlanOptions(isRsync);
    const hasDeleteWarning = Boolean(rsyncDelete?.checked);
    destinationPlanWarning?.classList.toggle("d-none", !hasDeleteWarning);
    if (destinationPlanWarningText) {
      destinationPlanWarningText.textContent = hasDeleteWarning
        ? "Dangerous option enabled: destination-only files and folders inside the selected folders will be permanently deleted before the operation completes. Review the destination carefully."
        : "";
    }
    destinationPlanConfirmed = true;
  }

  function renderDestinationPlanItems(items) {
    if (!destinationPlanItems) return;
    destinationPlanItems.replaceChildren();
    const finalDestinationPath = plannedDestinationPath();
    destinationPlanItems.appendChild(transferPlanSummary(items));
    if (destinationAction === "compress") {
      const flow = document.createElement("div");
      flow.className = "file-manager-transfer-plan-item";
      const sourceCard = transferPlanCard(
        "Archive contents",
        "bi-files",
        `${items.length} selected item${items.length === 1 ? "" : "s"}`,
      );
      const arrow = document.createElement("div");
      arrow.className = "file-manager-transfer-plan-arrow";
      arrow.innerHTML = '<i class="bi bi-arrow-right" aria-hidden="true"></i>';
      const targetCard = transferPlanCard("Archive", "bi-file-earmark-zip", plannedArchivePath());
      flow.append(sourceCard, arrow, targetCard);
      destinationPlanItems.appendChild(flow);
      return;
    }
    if (destinationAction === "uncompress") {
      const item = items[0];
      const flow = document.createElement("div");
      flow.className = "file-manager-transfer-plan-item";
      const sourceCard = transferPlanCard("Archive", "bi-file-earmark-zip", item?.path || "");
      const arrow = document.createElement("div");
      arrow.className = "file-manager-transfer-plan-arrow";
      arrow.innerHTML = '<i class="bi bi-arrow-right" aria-hidden="true"></i>';
      const targetCard = transferPlanCard("Extract into", "bi-folder2-open", finalDestinationPath);
      flow.append(sourceCard, arrow, targetCard);
      destinationPlanItems.appendChild(flow);
      return;
    }
    const visibleItems = items.slice(0, 50);
    visibleItems.forEach((item) => {
      const targetPath = joinPath(finalDestinationPath, item.name || basename(item.path));
      const flow = document.createElement("div");
      flow.className = "file-manager-transfer-plan-item";
      const sourceCard = transferPlanCard(
        "Source",
        item.kind === "folder" ? "bi-folder-fill" : fileIconClass(item),
        item.path,
      );
      const arrow = document.createElement("div");
      arrow.className = "file-manager-transfer-plan-arrow";
      arrow.innerHTML = '<i class="bi bi-arrow-right" aria-hidden="true"></i>';
      const targetCard = transferPlanCard("Destination", "bi-folder2-open", targetPath);
      flow.append(sourceCard, arrow, targetCard);
      destinationPlanItems.appendChild(flow);
    });
    if (items.length > visibleItems.length) {
      const more = document.createElement("div");
      more.className = "file-manager-transfer-plan-more";
      more.textContent = `${items.length - visibleItems.length} more selected item${items.length - visibleItems.length === 1 ? "" : "s"} included in this operation.`;
      destinationPlanItems.appendChild(more);
    }
  }

  function transferPlanSummary(items) {
    const folders = items.filter((item) => item.kind === "folder").length;
    const files = items.length - folders;
    const parts = [];
    if (files) parts.push(`${files} file${files === 1 ? "" : "s"}`);
    if (folders) parts.push(`${folders} folder${folders === 1 ? "" : "s"}`);
    const summary = document.createElement("div");
    summary.className = "file-manager-transfer-plan-summary";
    summary.innerHTML = '<i class="bi bi-check2-square" aria-hidden="true"></i><span></span>';
    summary.querySelector("span").textContent = `Selected: ${parts.join(" and ") || `${items.length} item${items.length === 1 ? "" : "s"}`}.`;
    return summary;
  }

  function renderDestinationPlanOptions(isRsync) {
    if (!destinationPlanOptions) return;
    destinationPlanOptions.replaceChildren();
    const newFolderName = normalizedDestinationNewFolderName();
    const options = destinationAction === "compress" ? [
      ["Archive format", "bi-speedometer2", compressionMethod?.selectedOptions?.[0]?.textContent?.trim() || "ZIP deflated"],
      ["Destination folder", "bi-folder-plus", newFolderName ? `Create "${newFolderName}" first` : "Use selected folder"],
      ["Archive name", "bi-file-earmark-zip", normalizedArchiveName()],
      ["Archive conflicts", "bi-file-earmark-text", conflictPolicy?.selectedOptions?.[0]?.textContent?.trim() || "Overwrite"]
    ] : destinationAction === "uncompress" ? [
      ["Destination folder", "bi-folder-plus", newFolderName ? `Create "${newFolderName}" first` : "Use selected folder"],
      ["Existing files", "bi-file-earmark-text", conflictPolicy?.selectedOptions?.[0]?.textContent?.trim() || "Overwrite"],
      ["Existing folders", "bi-folder-fill", folderConflictPolicy?.selectedOptions?.[0]?.textContent?.trim() || "Merge"],
      ["Archive type", "bi-file-earmark-zip", archiveTypeLabel(selectedItems()[0]?.name || "archive")]
    ] : [
      ["Method", "bi-gear", transferMethod?.selectedOptions?.[0]?.textContent?.trim() || "Standard"],
      ["Destination folder", "bi-folder-plus", newFolderName ? `Create "${newFolderName}" first` : "Use selected folder"],
      ["Files", "bi-file-earmark-text", conflictPolicy?.selectedOptions?.[0]?.textContent?.trim() || "Overwrite"],
      ["Directories", "bi-folder-fill", folderConflictPolicy?.selectedOptions?.[0]?.textContent?.trim() || "Merge"],
      ["Rsync delete", "bi-trash3", isRsync && rsyncDelete?.checked ? "Enabled · --delete" : "Disabled"]
    ];
    options.forEach(([label, icon, value]) => {
      const card = document.createElement("div");
      card.className = `file-manager-transfer-option${label === "Rsync delete" && isRsync && rsyncDelete?.checked ? " is-danger" : ""}`;
      const iconNode = document.createElement("i");
      iconNode.className = `bi ${icon}`;
      iconNode.setAttribute("aria-hidden", "true");
      const body = document.createElement("div");
      const title = document.createElement("div");
      title.className = "file-manager-transfer-option-label";
      title.textContent = label;
      const detail = document.createElement("div");
      detail.className = "file-manager-transfer-option-value";
      detail.textContent = value;
      body.append(title, detail);
      card.append(iconNode, body);
      destinationPlanOptions.appendChild(card);
    });
  }

  function plannedDestinationPath() {
    const newFolderName = normalizedDestinationNewFolderName();
    return newFolderName ? joinPath(destinationPath, newFolderName) : destinationPath;
  }

  function plannedArchivePath() {
    return joinPath(plannedDestinationPath(), normalizedArchiveName());
  }

  function normalizedArchiveName() {
    const name = (compressArchiveName?.value || "").trim();
    if (!name) return "";
    return archiveNameWithCurrentExtension(name);
  }

  function archiveNameWithCurrentExtension(name) {
    const extension = currentArchiveExtension();
    const archiveExtensions = [".tar.bz2", ".tar.gz", ".tar.xz", ".zip", ".tar"];
    const lowerName = name.toLowerCase();
    const matched = archiveExtensions.find((candidate) => lowerName.endsWith(candidate));
    if (matched) return `${name.slice(0, -matched.length)}${extension}`;
    return `${name}${extension}`;
  }

  function currentArchiveExtension() {
    return compressionMethod?.selectedOptions?.[0]?.dataset?.extension || ".zip";
  }

  function normalizeArchiveNameExtension() {
    if (!compressArchiveName) return;
    const name = compressArchiveName.value.trim();
    if (!name) return;
    compressArchiveName.value = archiveNameWithCurrentExtension(name);
  }

  function validateCompressOptions() {
    if (destinationAction !== "compress") return true;
    const name = (compressArchiveName?.value || "").trim();
    if (!name) {
      setCompressStatus("Archive name is required.", true);
      compressArchiveName?.focus();
      return false;
    }
    if (name === "." || name === ".." || /[\\/]/.test(name) || /[\n\r\0]/.test(name)) {
      setCompressStatus("Archive name cannot contain path separators or line breaks.", true);
      compressArchiveName?.focus();
      return false;
    }
    setCompressStatus("", false);
    return true;
  }

  function archiveTypeLabel(name) {
    const lowerName = String(name || "").toLowerCase();
    if (lowerName.endsWith(".zip")) return "ZIP";
    if (lowerName.endsWith(".tar")) return "TAR";
    if (lowerName.endsWith(".tar.gz") || lowerName.endsWith(".tgz")) return "TAR gzip";
    if (lowerName.endsWith(".tar.bz2") || lowerName.endsWith(".tbz2")) return "TAR BZIP2";
    if (lowerName.endsWith(".tar.xz") || lowerName.endsWith(".txz")) return "TAR XZ";
    return "Archive";
  }

  function setCompressStatus(message, isError) {
    if (!compressStatus) return;
    compressStatus.textContent = message || "";
    compressStatus.classList.toggle("d-none", !message);
    compressStatus.classList.toggle("is-error", Boolean(isError));
  }

  function defaultArchiveName() {
    const items = selectedItems();
    if (items.length === 1) {
      const base = (items[0].name || basename(items[0].path) || "archive").replace(/\.(tar\.bz2|tar\.gz|tar\.xz|zip|tar)$/i, "");
      return `${base}${currentArchiveExtension()}`;
    }
    return `archive${currentArchiveExtension()}`;
  }

  function transferPlanCard(label, iconClass, path) {
    const card = document.createElement("div");
    card.className = "file-manager-transfer-plan-card";
    const heading = document.createElement("div");
    heading.className = "file-manager-transfer-plan-card-label";
    heading.textContent = label;
    const body = document.createElement("div");
    body.className = "file-manager-transfer-plan-card-body";
    const icon = document.createElement("i");
    icon.className = `bi ${iconClass}`;
    icon.setAttribute("aria-hidden", "true");
    const value = document.createElement("span");
    value.className = "file-manager-transfer-plan-path";
    value.textContent = path;
    value.title = path;
    body.append(icon, value);
    card.append(heading, body);
    return card;
  }

  function joinPath(parent, name) {
    const base = String(parent || "/").replace(/\/+$/, "") || "/";
    return base === "/" ? `/${name}` : `${base}/${name}`;
  }

  function openDeleteModal() {
    const items = selectedItems();
    if (!items.length) return;
    renderDeleteModal(items);
    if (window.bootstrap && deleteModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(deleteModalElement).show();
    }
  }

  function renderDeleteModal(items) {
    if (deleteSummary) {
      const folders = items.filter((item) => item.kind === "folder").length;
      const files = items.length - folders;
      const parts = [];
      if (files) parts.push(`${files} file${files === 1 ? "" : "s"}`);
      if (folders) parts.push(`${folders} folder${folders === 1 ? "" : "s"}`);
      deleteSummary.textContent = `Selected: ${parts.join(" and ")}.`;
    }
    if (deleteConfirm) deleteConfirm.disabled = items.length === 0;
    if (!deleteList) return;
    deleteList.replaceChildren();
    items.slice(0, 20).forEach((item) => {
      const row = document.createElement("div");
      row.className = "file-manager-delete-item";

      const icon = document.createElement("span");
      icon.className = `file-manager-icon file-manager-icon-${item.kind === "folder" ? "folder" : "file"}`;
      icon.innerHTML = `<i class="bi ${item.kind === "folder" ? "bi-folder-fill" : fileIconClass(item)}"></i>`;

      const body = document.createElement("div");
      body.className = "min-w-0";

      const name = document.createElement("div");
      name.className = "file-manager-upload-name";
      name.textContent = item.name || basename(item.path);

      const path = document.createElement("div");
      path.className = "text-secondary small text-truncate";
      path.title = item.path || "";
      path.textContent = item.path || "";

      const meta = document.createElement("div");
      meta.className = "text-secondary small";
      meta.textContent = item.kind === "folder" ? "Folder" : `File · ${formatSize(item.size_bytes)}`;

      body.append(name, path, meta);
      row.append(icon, body);
      deleteList.appendChild(row);
    });

    if (items.length > 20) {
      const more = document.createElement("div");
      more.className = "file-manager-upload-more small";
      more.textContent = `${items.length - 20} more selected item${items.length - 20 === 1 ? "" : "s"}`;
      deleteList.appendChild(more);
    }
  }
