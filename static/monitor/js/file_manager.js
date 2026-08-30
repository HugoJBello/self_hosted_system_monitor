(function () {
  const page = document.querySelector("[data-file-manager-page]");
  if (!page) return;

  const rowsContainer = page.querySelector("[data-file-manager-rows]");
  const tableContainer = page.querySelector("[data-file-manager-table]");
  const gridContainer = page.querySelector("[data-file-manager-grid]");
  const fileArea = page.querySelector("[data-file-manager-area]");
  const currentBreadcrumbs = page.querySelector("[data-current-breadcrumbs]");
  const currentPathInput = page.querySelector("[data-current-path-input]");
  const returnPathInput = page.querySelector("[data-return-path-input]");
  const fileActionInput = page.querySelector("[data-file-action-input]");
  const itemCount = page.querySelector("[data-item-count]");
  const selectionCount = page.querySelector("[data-selection-count]");
  const sortField = page.querySelector("[data-sort-field]");
  const sortDirection = page.querySelector("[data-sort-direction]");
  const sortHeaders = page.querySelectorAll("[data-sort-header]");
  const fileSearchLink = page.querySelector("[data-file-search-link]");
  const parentButton = page.querySelector("[data-parent-button]");
  const viewModeToggle = page.querySelector("[data-view-mode-toggle]");
  const viewModeLabel = page.querySelector("[data-view-mode-label]");
  const multipleSelectToggle = page.querySelector("[data-multiple-select-toggle]");
  const singleClickToggle = page.querySelector("[data-single-click-toggle]");
  const selectedInputs = page.querySelector("[data-selected-paths-inputs]");
  const selectionActions = page.querySelectorAll("[data-selection-action]");
  const actionsToggle = page.querySelector("[data-actions-toggle]");
  const actionsMenu = actionsToggle?.nextElementSibling;
  const uncompressTrigger = page.querySelector("[data-uncompress-trigger]");
  const previewTrigger = page.querySelector("[data-preview-trigger]");
  const previewModalElement = page.querySelector("[data-preview-modal]");
  const previewTitle = page.querySelector("[data-preview-title]");
  const previewStage = page.querySelector("[data-preview-stage]");
  const previewStatus = page.querySelector("[data-preview-status]");
  const createFolderTrigger = page.querySelector("[data-create-folder-trigger]");
  const createFolderModalElement = page.querySelector("[data-create-folder-modal]");
  const createFolderName = page.querySelector("[data-create-folder-name]");
  const createFolderStatus = page.querySelector("[data-create-folder-status]");
  const createFolderSubmit = page.querySelector("[data-create-folder-submit]");
  const uploadTrigger = page.querySelector("[data-upload-trigger]");
  const uploadModalElement = page.querySelector("[data-upload-modal]");
  const uploadBreadcrumbs = page.querySelector("[data-upload-breadcrumbs]");
  const uploadFilesButton = page.querySelector("[data-upload-files-button]");
  const uploadFolderButton = page.querySelector("[data-upload-folder-button]");
  const uploadClearButton = page.querySelector("[data-upload-clear-button]");
  const uploadFilesInput = page.querySelector("[data-upload-files-input]");
  const uploadFolderInput = page.querySelector("[data-upload-folder-input]");
  const uploadDropzone = page.querySelector("[data-upload-dropzone]");
  const uploadWorkers = page.querySelector("[data-upload-workers]");
  const uploadChunkToggle = page.querySelector("[data-upload-chunk-toggle]");
  const uploadSelection = page.querySelector("[data-upload-selection]");
  const uploadList = page.querySelector("[data-upload-list]");
  const uploadStart = page.querySelector("[data-upload-start]");
  const uploadProgressWrap = page.querySelector("[data-upload-progress-wrap]");
  const uploadProgressBar = page.querySelector("[data-upload-progress-bar]");
  const uploadStatus = page.querySelector("[data-upload-status]");
  const downloadTrigger = page.querySelector("[data-download-trigger]");
  const downloadModalElement = page.querySelector("[data-download-modal]");
  const downloadSelection = page.querySelector("[data-download-selection]");
  const downloadProgressBar = page.querySelector("[data-download-progress-bar]");
  const downloadStatus = page.querySelector("[data-download-status]");
  const downloadLog = page.querySelector("[data-download-log]");
  const downloadReady = page.querySelector("[data-download-ready]");
  const downloadDetail = page.querySelector("[data-download-detail]");
  const destinationModalElement = page.querySelector("[data-destination-modal]");
  const destinationRows = page.querySelector("[data-destination-rows]");
  const destinationPathInput = page.querySelector("[data-destination-path-input]");
  const destinationNewFolderInput = page.querySelector("[data-destination-new-folder-input]");
  const destinationBreadcrumbs = page.querySelector("[data-destination-breadcrumbs]");
  const destinationTitle = page.querySelector("[data-destination-title]");
  const destinationUp = page.querySelector("[data-destination-up]");
  const destinationSubmit = page.querySelector("[data-destination-submit]");
  const destinationNewFolderToggle = page.querySelector("[data-destination-new-folder-toggle]");
  const destinationNewFolderFields = page.querySelector("[data-destination-new-folder-fields]");
  const destinationNewFolderName = page.querySelector("[data-destination-new-folder-name]");
  const destinationNewFolderStatus = page.querySelector("[data-destination-new-folder-status]");
  const compressOptions = page.querySelector("[data-compress-options]");
  const compressArchiveName = page.querySelector("[data-compress-archive-name]");
  const compressionMethod = page.querySelector("[data-compression-method]");
  const compressStatus = page.querySelector("[data-compress-status]");
  const transferMethodPanel = page.querySelector("[data-transfer-method-panel]");
  const transferMethod = page.querySelector("[data-transfer-method]");
  const destinationPickerUi = page.querySelector("[data-destination-picker-ui]");
  const destinationPlan = page.querySelector("[data-destination-plan]");
  const destinationPlanMethod = page.querySelector("[data-destination-plan-method]");
  const destinationPlanItems = page.querySelector("[data-destination-plan-items]");
  const destinationPlanOptions = page.querySelector("[data-destination-plan-options]");
  const destinationPlanWarning = page.querySelector("[data-destination-plan-warning]");
  const destinationPlanWarningText = page.querySelector("[data-destination-plan-warning-text]");
  const destinationPlanEdit = page.querySelector("[data-destination-plan-edit]");
  const rsyncOptions = page.querySelector("[data-rsync-options]");
  const rsyncDelete = page.querySelector("[data-rsync-delete]");
  const rsyncDeleteWarning = page.querySelector("[data-rsync-delete-warning]");
  const conflictPolicies = page.querySelector("[data-conflict-policies]");
  const conflictPolicy = page.querySelector("[data-conflict-policy]");
  const conflictPolicyLabel = page.querySelector("[data-conflict-policy-label]");
  const folderConflictPolicy = page.querySelector("[data-folder-conflict-policy]");
  const folderConflictPolicyPanel = page.querySelector("[data-folder-conflict-policy-panel]");
  const deleteTrigger = page.querySelector("[data-delete-trigger]");
  const deleteModalElement = page.querySelector("[data-delete-modal]");
  const deleteSummary = page.querySelector("[data-delete-summary]");
  const deleteList = page.querySelector("[data-delete-list]");
  const deleteConfirm = page.querySelector("[data-delete-confirm]");
  const errorBox = page.querySelector("[data-file-manager-error]");
  const fileManagerLoading = page.querySelector("[data-file-manager-loading]");
  const fileManagerLoadingLabel = page.querySelector("[data-file-manager-loading-label]");
  const destinationLoading = page.querySelector("[data-destination-loading]");
  const destinationSortField = page.querySelector("[data-destination-sort-field]");
  const destinationSortDirection = page.querySelector("[data-destination-sort-direction]");
  const listUrl = page.dataset.listUrl;
  const infoUrl = page.dataset.infoUrl;
  const informationTrigger = page.querySelector("[data-information-trigger]");
  const informationModalElement = page.querySelector("[data-information-modal]");
  const informationTitle = page.querySelector("[data-information-title]");
  const informationStatus = page.querySelector("[data-information-status]");
  const informationProgressWrap = page.querySelector("[data-information-progress-wrap]");
  const informationProgressBar = page.querySelector("[data-information-progress-bar]");
  const informationSummary = page.querySelector("[data-information-summary]");
  const informationItems = page.querySelector("[data-information-items]");
  const informationErrorsSection = page.querySelector("[data-information-errors-section]");
  const informationErrors = page.querySelector("[data-information-errors]");
  const selectedPaths = new Set();
  let currentPath = page.dataset.currentPath || "/";
  let parentPath = page.dataset.parentPath || "";
  let multipleSelectEnabled = false;
  let singleClickOpenEnabled = false;
  let destinationPath = "/";
  let destinationParentPath = "";
  let destinationPlanConfirmed = false;
  let destinationAction = "copy";
  let destinationNewFolderEnabled = false;
  let viewMode = "list";
  let uploadFiles = [];
  let uploadDragDepth = 0;
  let downloadPollTimer = null;
  let downloadAutoStarted = false;
  let actionsContextMode = false;
  let contextFolderPath = "";
  let activeActionTargetPath = "";
  let actionsMenuPlaceholder = null;
  let navigationRequestId = 0;
  let currentItems = [];
  let destinationSort = { field: "name", direction: "asc" };
  const actionsMenuParent = actionsMenu?.parentElement || null;
  const uploadChunkSize = 16 * 1024 * 1024;
  let informationPollTimer = null;
  const preferenceKeys = {
    viewMode: "fileManager.viewMode",
    multipleSelect: "fileManager.multipleSelect",
    singleClickOpen: "fileManager.singleClickOpen",
    sortField: "fileManager.sortField",
    sortDirection: "fileManager.sortDirection"
  };

  page.dataset.previousPath = currentPath;
  formatVisibleValues();
  renderBreadcrumbs(currentBreadcrumbs, currentPath, navigateTo);
  window.history.replaceState({ ...(window.history.state || {}), fileManagerPath: currentPath }, "", window.location.href);
  restoreSessionPreferences();
  currentItems = Array.from(rowsContainer?.querySelectorAll(".file-manager-item[data-path]:not([data-parent-row])") || []).map(itemFromElement);
  renderItems(currentItems);
  bindRows();
  updateSortDirectionButton(sortDirection, currentSortDirection());
  updateSortHeaders();
  updateFileSearchLink(currentPath);
  syncSelectionState();

  parentButton?.addEventListener("click", () => {
    if (parentPath) navigateTo(parentPath);
  });
  viewModeToggle?.addEventListener("click", () => setViewMode(viewMode === "list" ? "grid" : "list"));
  sortField?.addEventListener("change", () => applyFileSort());
  sortDirection?.addEventListener("click", () => toggleSortDirection());
  sortHeaders.forEach((header) => header.addEventListener("click", () => sortByHeader(header.dataset.sortHeader)));
  destinationSortField?.addEventListener("change", () => reloadDestinationWithSort());
  destinationSortDirection?.addEventListener("click", () => {
    destinationSort.direction = destinationSort.direction === "asc" ? "desc" : "asc";
    updateSortDirectionButton(destinationSortDirection, destinationSort.direction);
    reloadDestinationWithSort();
  });
  updateSortDirectionButton(destinationSortDirection, destinationSort.direction);
  fileArea?.addEventListener("contextmenu", handleFileAreaContextMenu);
  actionsToggle?.addEventListener("show.bs.dropdown", () => {
    restoreActionsMenu();
    if (!actionsContextMode) resetActionsMenuPosition();
  });
  actionsToggle?.addEventListener("hidden.bs.dropdown", () => {
    actionsContextMode = false;
    resetActionsMenuPosition();
  });
  actionsMenu?.addEventListener("click", (event) => {
    if (event.target.closest(".dropdown-item")) {
      window.requestAnimationFrame(closeContextActionsMenu);
    }
  });
  document.addEventListener("pointerdown", handleDocumentPointerDown, true);
  document.addEventListener("keydown", handleDocumentKeyDown);
  window.addEventListener("popstate", handleBrowserBack);
  informationTrigger?.addEventListener("click", openInformationModal);
  informationModalElement?.addEventListener("hidden.bs.modal", () => {
    stopInformationPolling();
    if (window.history.state?.fileManagerModal === "information") {
      const nextState = { ...(window.history.state || {}) };
      delete nextState.fileManagerModal;
      window.history.replaceState(nextState, "", window.location.href);
    }
  });
  previewTrigger?.addEventListener("click", () => {
    const item = selectedPreviewItem();
    if (item) openPreviewModal(item);
  });
  previewModalElement?.addEventListener("hidden.bs.modal", resetPreviewModal);
  createFolderModalElement?.addEventListener("shown.bs.modal", () => {
    createFolderName?.focus({ preventScroll: true });
  });

  multipleSelectToggle?.addEventListener("click", () => {
    setMultipleSelectEnabled(!multipleSelectEnabled);
  });
  singleClickToggle?.addEventListener("click", () => {
    setSingleClickOpenEnabled(!singleClickOpenEnabled);
  });
  createFolderTrigger?.addEventListener("click", openCreateFolderModal);
  uploadTrigger?.addEventListener("click", openUploadModal);
  uploadFilesButton?.addEventListener("click", () => uploadFilesInput?.click());
  uploadFolderButton?.addEventListener("click", () => uploadFolderInput?.click());
  uploadClearButton?.addEventListener("click", () => {
    clearUploadFiles();
    setUploadStatus("");
    setUploadProgress(0, true);
  });
  uploadFilesInput?.addEventListener("change", () => addUploadFiles(uploadFilesInput.files, uploadFilesInput));
  uploadFolderInput?.addEventListener("change", () => addUploadFiles(uploadFolderInput.files, uploadFolderInput));
  uploadDropzone?.addEventListener("dragenter", handleUploadDragEnter);
  uploadDropzone?.addEventListener("dragover", handleUploadDragOver);
  uploadDropzone?.addEventListener("dragleave", handleUploadDragLeave);
  uploadDropzone?.addEventListener("drop", handleUploadDrop);
  uploadDropzone?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      uploadFilesInput?.click();
    }
  });
  uploadStart?.addEventListener("click", () => {
    if (uploadFiles.length) startUpload();
  });
  downloadTrigger?.addEventListener("click", startDownloadPreparation);
  page.querySelectorAll("[data-destination-action]").forEach((button) => {
    button.addEventListener("click", () => openDestinationModal(button.dataset.destinationAction || "copy"));
  });
  transferMethod?.addEventListener("change", updateRsyncOptions);
  conflictPolicy?.addEventListener("change", updateRsyncOptions);
  folderConflictPolicy?.addEventListener("change", updateRsyncOptions);
  rsyncDelete?.addEventListener("change", updateRsyncOptions);
  destinationPlanEdit?.addEventListener("click", showDestinationPicker);
  compressArchiveName?.addEventListener("input", () => {
    setCompressStatus("", false);
    destinationPlanConfirmed = false;
  });
  compressionMethod?.addEventListener("change", () => {
    normalizeArchiveNameExtension();
    destinationPlanConfirmed = false;
  });
  destinationNewFolderToggle?.addEventListener("click", () => {
    setDestinationNewFolderEnabled(!destinationNewFolderEnabled, { focus: true });
  });
  destinationNewFolderName?.addEventListener("input", () => {
    setDestinationNewFolderStatus("", false);
    destinationPlanConfirmed = false;
    if (destinationNewFolderInput) destinationNewFolderInput.value = normalizedDestinationNewFolderName();
  });
  deleteTrigger?.addEventListener("click", openDeleteModal);
  destinationUp?.addEventListener("click", () => {
    if (destinationParentPath) loadDestination(destinationParentPath);
  });
  page.addEventListener("submit", async (event) => {
    const action = submitAction(event.submitter);
    page.querySelectorAll("[data-pending-submit-marker]").forEach((marker) => marker.remove());
    if (action === "mkdir") {
      event.preventDefault();
      await submitCreateFolder();
      return;
    }
    if (["copy", "move", "compress", "uncompress"].includes(action) && destinationModalElement?.classList.contains("show") && !destinationPlanConfirmed) {
      event.preventDefault();
      showDestinationPlan();
      return;
    }
    if (fileActionInput) fileActionInput.value = action;
    if (action === "mkdir" && currentPathInput) {
      currentPathInput.value = activeActionTargetPath || currentPath;
    } else if (currentPathInput) {
      currentPathInput.value = currentPath;
    }
    if (returnPathInput) returnPathInput.value = currentPath;
    syncSelectedInputs();
  });

  function submitAction(submitter) {
    if (createFolderModalElement?.classList.contains("show")) return "mkdir";
    if (deleteModalElement?.classList.contains("show")) return "delete";
    if (destinationModalElement?.classList.contains("show")) return destinationAction;
    if (submitter?.value) return submitter.value;
    return "";
  }

  async function submitCreateFolder() {
    const folderName = (createFolderName?.value || "").trim();
    const targetPath = activeActionTargetPath || currentPath || "/";
    if (!folderName) {
      setCreateFolderStatus("Folder name is required.", true);
      createFolderName?.focus();
      return;
    }

    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    const body = new URLSearchParams();
    body.set("csrfmiddlewaretoken", csrfInput?.value || "");
    body.set("current_path", targetPath);
    body.set("return_path", currentPath || "/");
    body.set("folder_name", folderName);
    body.set("file_action", "mkdir");
    if (createFolderSubmit) createFolderSubmit.disabled = true;
    setCreateFolderStatus("Creating folder...", false);
    try {
      const response = await fetch(page.action || window.location.href, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
        },
        body,
      });
      let payload = {};
      try {
        payload = await response.json();
      } catch (_) {
        throw new Error(`Could not create folder (HTTP ${response.status}).`);
      }
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `Could not create folder (HTTP ${response.status}).`);
      }
      setCreateFolderStatus(`Created ${payload.item?.path || folderName}.`, false);
      activeActionTargetPath = "";
      if (window.bootstrap && createFolderModalElement) {
        window.bootstrap.Modal.getOrCreateInstance(createFolderModalElement).hide();
      }
      await navigateTo(targetPath);
    } catch (error) {
      setCreateFolderStatus(error.message || "Could not create folder.", true);
      if (createFolderSubmit) createFolderSubmit.disabled = false;
    }
  }

  function setCreateFolderStatus(message, isError) {
    if (!createFolderStatus) return;
    createFolderStatus.textContent = message || "";
    createFolderStatus.classList.toggle("d-none", !message);
    createFolderStatus.classList.toggle("is-error", Boolean(isError));
  }

  function bindRows() {
    page.querySelectorAll(".file-manager-item[data-path]").forEach((row) => {
      if (row.dataset.bound === "1" || row.dataset.parentRow) return;
      row.dataset.bound = "1";
      row.addEventListener("click", (event) => handleItemClick(row, event));
      row.addEventListener("dblclick", (event) => {
        if (!singleClickOpenEnabled && !selectionModifierPressed(event)) openItem(row);
      });
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          if (multipleSelectEnabled || selectionModifierPressed(event)) {
            toggleSelection(row);
          } else {
            openItem(row);
          }
        }
        if (event.key === " ") {
          event.preventDefault();
          if (multipleSelectEnabled) {
            toggleSelection(row);
          } else {
            selectSingleItem(row);
          }
        }
      });
    });
  }

  function selectionModifierPressed(event) {
    return Boolean(event?.ctrlKey || event?.metaKey);
  }

  function handleItemClick(item, event) {
    if (multipleSelectEnabled || selectionModifierPressed(event)) {
      toggleSelection(item);
      return;
    }
    if (singleClickOpenEnabled) {
      openItem(item);
      return;
    }
    selectSingleItem(item);
  }

  function openItem(item) {
    if (!item || item.dataset.parentRow) return;
    if (item.dataset.kind === "folder") {
      navigateTo(item.dataset.path);
      return;
    }
    if (item.dataset.previewUrl) {
      openPreviewModal(item);
    }
  }

  function handleFileAreaContextMenu(event) {
    event.preventDefault();
    const item = event.target.closest(".file-manager-item[data-path]");
    if (item && fileArea.contains(item) && !item.dataset.parentRow) {
      selectContextItem(item);
      contextFolderPath = item.dataset.kind === "folder" ? item.dataset.path || "" : "";
    } else {
      clearSelection();
      contextFolderPath = "";
    }
    showActionsMenuAt(event.clientX, event.clientY);
  }

  function selectContextItem(item) {
    const path = item.dataset.path || "";
    if (!path) return;
    if (!(selectedPaths.has(path) && selectedPaths.size > 1)) {
      selectedPaths.clear();
      selectedPaths.add(path);
    }
    syncSelectionState();
  }

  function showActionsMenuAt(clientX, clientY) {
    if (!actionsToggle || !actionsMenu) return;
    if (window.bootstrap) {
      window.bootstrap.Dropdown.getOrCreateInstance(actionsToggle).hide();
    }
    actionsContextMode = true;
    moveActionsMenuToBody();
    prepareActionsMenuPosition(clientX, clientY);
    actionsMenu.classList.add("show");
    actionsToggle.setAttribute("aria-expanded", "true");
    window.requestAnimationFrame(() => positionActionsMenu(clientX, clientY));
  }

  function prepareActionsMenuPosition(clientX, clientY) {
    if (!actionsMenu) return;
    actionsMenu.classList.add("file-manager-context-actions");
    setActionsMenuCoordinates(clientX, clientY);
  }

  function positionActionsMenu(clientX, clientY) {
    if (!actionsMenu) return;
    const padding = 8;
    const rect = actionsMenu.getBoundingClientRect();
    const left = Math.min(Math.max(clientX, padding), window.innerWidth - rect.width - padding);
    const top = Math.min(Math.max(clientY, padding), window.innerHeight - rect.height - padding);
    setActionsMenuCoordinates(Math.max(left, padding), Math.max(top, padding));
  }

  function resetActionsMenuPosition() {
    if (!actionsMenu) return;
    actionsMenu.classList.remove("file-manager-context-actions");
    ["left", "top", "right", "bottom", "position", "transform", "margin"].forEach((property) => {
      actionsMenu.style.removeProperty(property);
    });
  }

  function setActionsMenuCoordinates(left, top) {
    if (!actionsMenu) return;
    actionsMenu.style.setProperty("left", `${left}px`, "important");
    actionsMenu.style.setProperty("top", `${top}px`, "important");
    actionsMenu.style.setProperty("right", "auto", "important");
    actionsMenu.style.setProperty("bottom", "auto", "important");
  }

  function moveActionsMenuToBody() {
    if (!actionsMenu || actionsMenu.parentElement === document.body) return;
    actionsMenuPlaceholder = document.createComment("file-manager-actions-menu");
    actionsMenu.parentElement?.insertBefore(actionsMenuPlaceholder, actionsMenu);
    document.body.appendChild(actionsMenu);
  }

  function restoreActionsMenu() {
    if (!actionsMenu || !actionsMenuPlaceholder) return;
    if (actionsMenuPlaceholder.parentNode) {
      actionsMenuPlaceholder.parentNode.insertBefore(actionsMenu, actionsMenuPlaceholder);
      actionsMenuPlaceholder.remove();
    } else if (actionsMenuParent) {
      actionsMenuParent.appendChild(actionsMenu);
    }
    actionsMenuPlaceholder = null;
  }

  function closeContextActionsMenu() {
    if (!actionsContextMode || !actionsMenu) return;
    actionsContextMode = false;
    contextFolderPath = "";
    actionsMenu.classList.remove("show");
    actionsToggle?.setAttribute("aria-expanded", "false");
    resetActionsMenuPosition();
    restoreActionsMenu();
  }

  function handleDocumentPointerDown(event) {
    if (!actionsContextMode || !actionsMenu) return;
    if (actionsMenu.contains(event.target)) return;
    closeContextActionsMenu();
  }

  function handleDocumentKeyDown(event) {
    if (event.key === "Escape") closeContextActionsMenu();
  }

  async function navigateTo(path, { updateHistory = true } = {}) {
    if (!path) return;
    const requestId = ++navigationRequestId;
    setError("");
    clearSelection();
    activeActionTargetPath = "";
    contextFolderPath = "";
    page.classList.add("is-loading");
    setFileManagerLoading(true, "Loading folder...");
    try {
      const url = new URL(listUrl, window.location.origin);
      url.searchParams.set("path", path);
      url.searchParams.set("sort", sortField?.value || "name");
      url.searchParams.set("direction", currentSortDirection());
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" }
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      if (requestId !== navigationRequestId) return;
      currentPath = payload.path || "/";
      parentPath = payload.parent_path || "";
      page.dataset.currentPath = currentPath;
      page.dataset.parentPath = parentPath;
      if (currentPathInput) currentPathInput.value = currentPath;
      currentItems = payload.items || [];
      renderItems(currentItems);
      renderBreadcrumbs(currentBreadcrumbs, currentPath, navigateTo);
      renderBreadcrumbs(uploadBreadcrumbs, currentPath, navigateTo);
      updateFileSearchLink(currentPath);
      if (itemCount) itemCount.textContent = String((payload.items || []).length);
      if (parentButton) parentButton.disabled = !parentPath;
      if (updateHistory && currentPath !== page.dataset.previousPath) {
        window.history.pushState({ fileManagerPath: currentPath }, "", `${window.location.pathname}?path=${encodeURIComponent(currentPath)}&sort=${encodeURIComponent(sortField?.value || "name")}&direction=${encodeURIComponent(currentSortDirection())}`);
      }
      page.dataset.previousPath = currentPath;
    } catch (error) {
      setError(error.message || "Could not open this folder.");
    } finally {
      if (requestId === navigationRequestId) {
        page.classList.remove("is-loading");
        setFileManagerLoading(false);
      }
    }
  }

  function handleBrowserBack(event) {
    if (event.state?.fileManagerDestinationPath) {
      if (destinationModalElement && !destinationModalElement.classList.contains("show") && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(destinationModalElement).show();
      }
      loadDestination(event.state.fileManagerDestinationPath, { updateHistory: false });
      return;
    }
    if (destinationModalElement?.classList.contains("show")) {
      window.bootstrap?.Modal.getOrCreateInstance(destinationModalElement).hide();
      return;
    }
    const openModal = [
      informationModalElement,
      previewModalElement,
      createFolderModalElement,
      uploadModalElement,
      downloadModalElement,
      deleteModalElement,
    ].find((element) => element?.classList.contains("show"));
    if (openModal) {
      window.bootstrap?.Modal.getOrCreateInstance(openModal).hide();
      return;
    }
    const url = new URL(window.location.href);
    if (sortField && url.searchParams.has("sort")) sortField.value = url.searchParams.get("sort");
    if (sortDirection && url.searchParams.has("direction")) sortDirection.dataset.direction = url.searchParams.get("direction");
    updateSortDirectionButton(sortDirection, currentSortDirection());
    navigateTo(url.searchParams.get("path") || "/", { updateHistory: false });
  }

  function setFileManagerLoading(isLoading, label) {
    if (!fileManagerLoading) return;
    fileManagerLoading.classList.toggle("d-none", !isLoading);
    fileManagerLoading.setAttribute("aria-busy", isLoading ? "true" : "false");
    if (fileManagerLoadingLabel && label) fileManagerLoadingLabel.textContent = label;
  }

  function renderItems(items) {
    const sortedItems = sortFileEntries(items, sortField?.value || "name", currentSortDirection());
    rowsContainer.innerHTML = "";
    if (gridContainer) gridContainer.innerHTML = "";
    if (parentPath) {
      rowsContainer.appendChild(parentRow(parentPath, "file-manager-row file-manager-item file-manager-parent-row", () => navigateTo(parentPath)));
      gridContainer?.appendChild(parentTile(parentPath, () => navigateTo(parentPath)));
    }
    if (!sortedItems.length) {
      const empty = document.createElement("div");
      empty.className = "file-manager-empty";
      empty.textContent = "No items in this location.";
      rowsContainer.appendChild(empty);
      return;
    }

    sortedItems.forEach((item) => {
      rowsContainer.appendChild(itemRow(item));
      gridContainer?.appendChild(itemTile(item));
    });
    bindRows();
    syncSelectionState();
  }

  function currentSortDirection() {
    return sortDirection?.dataset.direction || "asc";
  }

  function applyFileSort() {
    saveSortPreferences();
    updateSortDirectionButton(sortDirection, currentSortDirection());
    updateSortHeaders();
    renderItems(currentItems);
  }

  function toggleSortDirection() {
    const nextDirection = currentSortDirection() === "asc" ? "desc" : "asc";
    if (sortDirection) sortDirection.dataset.direction = nextDirection;
    applyFileSort();
  }

  function sortByHeader(field) {
    if (!sortField || !sortDirection) return;
    const nextDirection = sortField.value === field && currentSortDirection() === "asc" ? "desc" : "asc";
    sortField.value = field;
    sortDirection.dataset.direction = nextDirection;
    applyFileSort();
  }

  function updateSortHeaders() {
    const activeField = sortField?.value || "name";
    const activeDirection = currentSortDirection();
    sortHeaders.forEach((header) => {
      const isActive = header.dataset.sortHeader === activeField;
      header.setAttribute("aria-sort", isActive ? (activeDirection === "desc" ? "descending" : "ascending") : "none");
      const icon = header.querySelector("i");
      if (icon) icon.className = `bi ${isActive ? (activeDirection === "desc" ? "bi-arrow-down" : "bi-arrow-up") : "bi-arrow-down-up"}`;
    });
  }

  function saveSortPreferences() {
    saveSessionPreference(preferenceKeys.sortField, sortField?.value || "name");
    saveSessionPreference(preferenceKeys.sortDirection, currentSortDirection());
  }

  function reloadDestinationWithSort() {
    destinationSort.field = destinationSortField?.value || "name";
    loadDestination(destinationPath || "/", { updateHistory: false });
  }

  function updateSortDirectionButton(button, direction) {
    if (!button) return;
    const descending = direction === "desc";
    button.dataset.direction = direction;
    button.setAttribute("aria-label", descending ? "Sort descending" : "Sort ascending");
    button.title = descending ? "Sort descending" : "Sort ascending";
    const icon = button.querySelector("i");
    if (icon) icon.className = `bi ${descending ? "bi-sort-alpha-up" : "bi-sort-alpha-down"}`;
  }

  function sortFileEntries(items, field, direction) {
    const descending = direction === "desc";
    return Array.from(items || []).sort((left, right) => {
      const leftFolder = Boolean(left.is_dir || left.kind === "folder");
      const rightFolder = Boolean(right.is_dir || right.kind === "folder");
      if (leftFolder !== rightFolder) return leftFolder ? -1 : 1;

      const leftValue = sortValue(left, field);
      const rightValue = sortValue(right, field);
      if (leftValue < rightValue) return descending ? 1 : -1;
      if (leftValue > rightValue) return descending ? -1 : 1;

      const nameComparison = String(left.name || "").localeCompare(
        String(right.name || ""),
        undefined,
        { sensitivity: "base" },
      );
      return descending ? -nameComparison : nameComparison;
    });
  }

  function sortValue(item, field) {
    if (field === "size") return item.size_bytes == null || item.size_bytes === "" ? -1 : Number(item.size_bytes);
    if (field === "modified") return item.modified_at || "";
    if (field === "kind") return item.kind || (item.is_dir ? "folder" : "file");
    return String(item[field] || "").toLowerCase();
  }

  function itemRow(item) {
    const row = document.createElement("button");
    const kind = item.kind || (item.is_dir ? "folder" : "file");
    row.type = "button";
    row.className = "file-manager-row file-manager-item";
    setItemDataset(row, item, kind);
    row.setAttribute("role", "row");
    row.setAttribute("aria-selected", "false");
    row.innerHTML = `
        <span class="file-manager-select-cell" role="cell">
          <span class="file-manager-checkbox" aria-hidden="true"><i class="bi bi-check"></i></span>
        </span>
        <div class="file-manager-name" role="cell">
          <span class="file-manager-icon file-manager-icon-${escapeAttribute(kind)}"><i class="bi ${kind === "folder" ? "bi-folder-fill" : "bi-file-earmark-text"}"></i></span>
          <span class="text-truncate"></span>
          ${item.is_mounted ? '<span class="file-manager-chip">mounted</span>' : ""}
          ${item.is_symlink ? '<span class="file-manager-chip">link</span>' : ""}
        </div>
        <div role="cell">${escapeHtml(titleCase(kind))}</div>
        <div role="cell" data-size-bytes="${escapeAttribute(item.size_bytes ?? "")}">${formatSize(item.size_bytes)}</div>
        <div role="cell" data-file-date="${escapeAttribute(item.modified_at || "")}">${formatDate(item.modified_at) || "-"}</div>
        <div role="cell">${escapeHtml(ownerLabel(item))}</div>
        <div role="cell"><code>${escapeHtml(item.permissions || "-")}</code></div>
      `;
    row.querySelector(".text-truncate").textContent = item.name || "";
    return row;
  }

  function itemTile(item) {
    const tile = document.createElement("button");
    const kind = item.kind || (item.is_dir ? "folder" : "file");
    tile.type = "button";
    tile.className = "file-manager-tile file-manager-item";
    setItemDataset(tile, item, kind);
    tile.setAttribute("aria-selected", "false");
    tile.innerHTML = `
      <span class="file-manager-checkbox" aria-hidden="true"><i class="bi bi-check"></i></span>
      <span class="file-manager-tile-preview">${tilePreviewHtml(item, kind)}</span>
      <span class="file-manager-tile-name"></span>
      <span class="file-manager-tile-meta">${escapeHtml(tileMeta(item, kind))}</span>
    `;
    tile.querySelector(".file-manager-tile-name").textContent = item.name || "";
    return tile;
  }

  function setItemDataset(element, item, kind) {
    element.dataset.path = item.path || "";
    element.dataset.name = item.name || "";
    element.dataset.kind = kind;
    element.dataset.mediaKind = item.media_kind || "";
    element.dataset.contentType = item.content_type || "";
    element.dataset.previewUrl = item.preview_url || "";
    element.dataset.sizeBytesValue = item.size_bytes ?? "";
    element.dataset.modifiedAt = item.modified_at || "";
    element.dataset.owner = item.owner || "";
    element.dataset.group = item.group || "";
    element.dataset.permissions = item.permissions || "";
    element.dataset.mounted = item.is_mounted ? "1" : "0";
    element.dataset.symlink = item.is_symlink ? "1" : "0";
  }

  function tilePreviewHtml(item, kind) {
    if (item.media_kind === "image" && item.preview_url) {
      return `<img src="${escapeAttribute(item.preview_url)}" alt="" loading="lazy">`;
    }
    if (kind === "folder") return '<i class="bi bi-folder-fill"></i>';
    return `<i class="bi ${fileIconClass(item)}"></i>`;
  }

  function fileIconClass(item) {
    const contentType = item.content_type || "";
    const name = String(item.name || "").toLowerCase();
    if (item.media_kind === "video" || contentType.startsWith("video/")) return "bi-file-earmark-play";
    if (item.media_kind === "text" || contentType.startsWith("text/")) return "bi-file-earmark-text";
    if (contentType.startsWith("audio/")) return "bi-file-earmark-music";
    if (contentType === "application/pdf" || name.endsWith(".pdf")) return "bi-file-earmark-pdf";
    if (contentType.includes("zip") || contentType.includes("compressed") || /\.(zip|7z|rar|tar|gz|bz2|xz)$/.test(name)) return "bi-file-earmark-zip";
    if (/\.(csv|xls|xlsx|ods)$/.test(name)) return "bi-file-earmark-spreadsheet";
    if (/\.(doc|docx|odt|md|rtf)$/.test(name)) return "bi-file-earmark-richtext";
    if (/\.(py|js|ts|css|html|xml|json|yaml|yml|sh|go|rs|java|c|cpp|h)$/.test(name)) return "bi-file-earmark-code";
    return "bi-file-earmark";
  }

  function tileMeta(item, kind) {
    if (kind === "folder") return item.is_mounted ? "Mounted folder" : "Folder";
    return `${titleCase(item.media_kind || "file")} · ${formatSize(item.size_bytes)}`;
  }

  function insertInitialParentRow() {
    if (!parentPath || !rowsContainer || rowsContainer.querySelector("[data-parent-row]")) return;
    rowsContainer.insertBefore(
      parentRow(parentPath, "file-manager-row file-manager-item file-manager-parent-row", () => navigateTo(parentPath)),
      rowsContainer.firstChild
    );
  }

  function renderInitialGrid() {
    if (!gridContainer) return;
    gridContainer.innerHTML = "";
    if (parentPath) gridContainer.appendChild(parentTile(parentPath, () => navigateTo(parentPath)));
    rowsContainer.querySelectorAll("[data-path]:not([data-parent-row])").forEach((row) => {
      gridContainer.appendChild(itemTile(itemFromElement(row)));
    });
  }

  function parentRow(path, className, handler) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = className;
    row.dataset.parentRow = "true";
    row.innerHTML = `
      <span class="file-manager-select-cell" role="cell"></span>
      <div class="file-manager-name" role="cell">
        <span class="file-manager-icon file-manager-icon-parent"><i class="bi bi-arrow-up-short"></i></span>
        <span class="text-truncate">..</span>
      </div>
      <div role="cell">Parent</div>
      <div role="cell">-</div>
      <div role="cell">-</div>
      <div role="cell">-</div>
      <div role="cell"><code>-</code></div>
    `;
    row.addEventListener("click", handler);
    row.addEventListener("dblclick", handler);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        handler();
      }
    });
    return row;
  }

  function parentTile(path, handler) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "file-manager-tile file-manager-item file-manager-parent-row";
    tile.dataset.parentRow = "true";
    tile.dataset.path = path;
    tile.dataset.kind = "folder";
    tile.innerHTML = `
      <span class="file-manager-tile-preview"><i class="bi bi-arrow-up-short"></i></span>
      <span class="file-manager-tile-name">..</span>
      <span class="file-manager-tile-meta">Parent</span>
    `;
    tile.addEventListener("click", handler);
    tile.addEventListener("dblclick", handler);
    return tile;
  }

  function itemFromElement(element) {
    return {
      path: element.dataset.path || "",
      name: element.dataset.name || "",
      kind: element.dataset.kind || "file",
      is_dir: element.dataset.kind === "folder",
      is_mounted: element.dataset.mounted === "1",
      is_symlink: element.dataset.symlink === "1",
      size_bytes: element.dataset.sizeBytesValue || "",
      modified_at: element.dataset.modifiedAt || "",
      owner: element.dataset.owner || "",
      group: element.dataset.group || "",
      permissions: element.dataset.permissions || "",
      media_kind: element.dataset.mediaKind || "",
      content_type: element.dataset.contentType || "",
      preview_url: element.dataset.previewUrl || ""
    };
  }

  function setViewMode(mode) {
    viewMode = mode === "grid" ? "grid" : "list";
    page.classList.toggle("is-grid-view", viewMode === "grid");
    page.classList.toggle("is-list-view", viewMode === "list");
    tableContainer?.classList.toggle("d-none", viewMode === "grid");
    gridContainer?.classList.toggle("d-none", viewMode !== "grid");
    viewModeToggle?.setAttribute("aria-pressed", viewMode === "grid" ? "true" : "false");
    if (viewModeLabel) viewModeLabel.textContent = viewMode === "grid" ? "List" : "Grid";
    const icon = viewModeToggle?.querySelector("i");
    if (icon) icon.className = `bi ${viewMode === "grid" ? "bi-list-ul" : "bi-grid-3x3-gap"}`;
    saveSessionPreference(preferenceKeys.viewMode, viewMode);
  }

  function setMultipleSelectEnabled(enabled) {
    multipleSelectEnabled = Boolean(enabled);
    page.classList.toggle("is-selecting", multipleSelectEnabled);
    multipleSelectToggle?.setAttribute("aria-pressed", multipleSelectEnabled ? "true" : "false");
    multipleSelectToggle?.classList.toggle("active", multipleSelectEnabled);
    if (!multipleSelectEnabled) clearSelection();
    saveSessionPreference(preferenceKeys.multipleSelect, multipleSelectEnabled ? "1" : "0");
    syncSelectionState();
  }

  function setSingleClickOpenEnabled(enabled) {
    singleClickOpenEnabled = Boolean(enabled);
    page.classList.toggle("is-single-click-open", singleClickOpenEnabled);
    singleClickToggle?.setAttribute("aria-pressed", singleClickOpenEnabled ? "true" : "false");
    singleClickToggle?.classList.toggle("active", singleClickOpenEnabled);
    if (singleClickOpenEnabled && !multipleSelectEnabled) clearSelection();
    saveSessionPreference(preferenceKeys.singleClickOpen, singleClickOpenEnabled ? "1" : "0");
  }

  function restoreSessionPreferences() {
    const storedSortField = loadSessionPreference(preferenceKeys.sortField);
    const storedSortDirection = loadSessionPreference(preferenceKeys.sortDirection);
    if (sortField && storedSortField) sortField.value = storedSortField;
    if (sortDirection && ["asc", "desc"].includes(storedSortDirection)) sortDirection.dataset.direction = storedSortDirection;
    const storedViewMode = loadSessionPreference(preferenceKeys.viewMode);
    if (storedViewMode === "grid" || storedViewMode === "list") {
      setViewMode(storedViewMode);
    }
    setMultipleSelectEnabled(loadSessionPreference(preferenceKeys.multipleSelect) === "1");
    setSingleClickOpenEnabled(loadSessionPreference(preferenceKeys.singleClickOpen) === "1");
    saveSortPreferences();
  }

  function updateFileSearchLink(path) {
    if (!fileSearchLink) return;
    const url = new URL(fileSearchLink.href, window.location.origin);
    url.searchParams.set("path", path || "/");
    fileSearchLink.href = url.toString();
  }

  function saveSessionPreference(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
    } catch (_) {
    }
  }

  function loadSessionPreference(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function selectSingleItem(row) {
    const path = row.dataset.path || "";
    if (!path) return;
    selectedPaths.clear();
    selectedPaths.add(path);
    syncSelectionState();
  }

  function toggleSelection(row) {
    const path = row.dataset.path || "";
    if (!path) return;
    if (selectedPaths.has(path)) {
      selectedPaths.delete(path);
    } else {
      selectedPaths.add(path);
    }
    syncSelectionState();
  }

  function clearSelection() {
    selectedPaths.clear();
    syncSelectionState();
  }

  function syncSelectionState() {
    page.querySelectorAll(".file-manager-item[data-path]").forEach((item) => {
      if (item.dataset.parentRow) return;
      const selected = selectedPaths.has(item.dataset.path || "");
      item.classList.toggle("is-selected", selected);
      item.setAttribute("aria-selected", selected ? "true" : "false");
    });
    const selectedCount = selectedPaths.size;
    syncSelectedInputs();
    selectionActions.forEach((button) => {
      button.disabled = selectedCount === 0;
    });
    updateUncompressAction(selectedCount);
    if (selectionCount) {
      selectionCount.textContent = selectedCount ? `${selectedCount} selected` : "";
      selectionCount.classList.toggle("d-none", !multipleSelectEnabled && selectedCount < 2);
    }
    if (previewTrigger) {
      previewTrigger.disabled = !selectedPreviewItem();
    }
  }

  function syncSelectedInputs() {
    if (!selectedInputs) return;
    selectedInputs.innerHTML = "";
    selectedPaths.forEach((path) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "selected_paths";
      input.value = path;
      selectedInputs.appendChild(input);
    });
  }

  function openInformationModal() {
    const paths = informationTargetPaths();
    if (!paths.length) return;
    resetInformationModal(paths);
    window.history.pushState(
      { ...(window.history.state || {}), fileManagerModal: "information" },
      "",
      window.location.href,
    );
    if (window.bootstrap && informationModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(informationModalElement).show();
    }
    requestInformation(paths);
  }

  function informationTargetPaths() {
    return selectedPaths.size ? Array.from(selectedPaths) : [currentPath || "/"];
  }

  function resetInformationModal(paths) {
    stopInformationPolling();
    if (informationTitle) {
      informationTitle.textContent = paths.length === 1 ? basename(paths[0]) : `${paths.length} selected items`;
    }
    setInformationStatus("Loading basic metadata...");
    setInformationScanning(false);
    if (informationSummary) informationSummary.replaceChildren();
    if (informationItems) informationItems.innerHTML = '<div class="file-manager-empty">Loading information...</div>';
    renderInformationErrors([]);
  }

  function requestInformation(paths) {
    const formData = fileManagerFormData();
    formData.append("current_path", currentPath || "/");
    paths.forEach((path) => formData.append("selected_paths", path));
    postInformation(formData)
      .then(updateInformationModal)
      .catch((error) => {
        setInformationStatus(error.message || "Could not load information.", true);
        setInformationScanning(false);
      });
  }

  function pollInformation(sessionId) {
    const formData = fileManagerFormData();
    formData.append("session_id", sessionId);
    postInformation(formData)
      .then(updateInformationModal)
      .catch((error) => {
        setInformationStatus(error.message || "Could not continue scanning.", true);
        stopInformationPolling();
      });
  }

  function postInformation(formData) {
    return fetch(infoUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: formData
    }).then(async (response) => {
      const body = await response.text();
      let payload;
      try {
        payload = JSON.parse(body);
      } catch (_error) {
        if (response.redirected || /<\s*!doctype|<html[\s>]/i.test(body)) {
          throw new Error("The session may have expired. Reload the page and try again.");
        }
        throw new Error(`Information returned an invalid response (HTTP ${response.status}).`);
      }
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      return payload;
    });
  }

  function updateInformationModal(payload) {
    renderInformationSummary(payload.aggregate || {});
    renderInformationItems(payload.items || []);
    renderInformationErrors(payload.errors || []);
    if (payload.complete) {
      setInformationStatus("Information complete.");
      setInformationScanning(false);
      stopInformationPolling();
      return;
    }
    const aggregate = payload.aggregate || {};
    setInformationStatus(`Scanning folders... ${aggregate.scanned_entries || 0} entries read.`);
    setInformationScanning(true);
    stopInformationPolling();
    informationPollTimer = window.setTimeout(() => pollInformation(payload.session_id), 120);
  }

  function stopInformationPolling() {
    if (!informationPollTimer) return;
    window.clearTimeout(informationPollTimer);
    informationPollTimer = null;
  }

  function setInformationStatus(message, isError) {
    if (!informationStatus) return;
    informationStatus.textContent = message || "";
    informationStatus.classList.toggle("is-error", Boolean(isError));
  }

  function setInformationScanning(scanning) {
    informationProgressWrap?.classList.toggle("d-none", !scanning);
    if (informationProgressBar) {
      informationProgressBar.style.width = scanning ? "100%" : "0%";
      informationProgressBar.textContent = scanning ? "Scanning" : "";
    }
  }

  function renderInformationSummary(aggregate) {
    if (!informationSummary) return;
    const cards = [
      ["Selected", aggregate.selected_count || 0],
      ["Files", aggregate.files || 0],
      ["Folders", aggregate.folders || 0],
      ["Size", formatSize(aggregate.size_bytes || 0)],
      ["Allocated", formatSize(aggregate.allocated_bytes || 0)],
      ["Scanned", aggregate.scanned_entries || 0],
      ["Symlinks", aggregate.symlinks || 0],
      ["Unreadable", aggregate.unreadable_directories || 0],
    ];
    informationSummary.replaceChildren();
    cards.forEach(([label, value]) => {
      const card = document.createElement("div");
      card.className = "file-manager-info-card";
      card.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
      informationSummary.appendChild(card);
    });
  }

  function renderInformationItems(items) {
    if (!informationItems) return;
    informationItems.replaceChildren();
    if (!items.length) {
      informationItems.innerHTML = '<div class="file-manager-empty">No information available.</div>';
      return;
    }
    items.forEach((item) => informationItems.appendChild(informationItemRow(item)));
  }

  function informationItemRow(item) {
    const row = document.createElement("div");
    row.className = "file-manager-info-item";

    const icon = document.createElement("span");
    icon.className = `file-manager-icon file-manager-icon-${item.kind === "folder" ? "folder" : "file"}`;
    icon.innerHTML = `<i class="bi ${item.kind === "folder" ? "bi-folder-fill" : fileIconClass(item)}"></i>`;

    const body = document.createElement("div");
    body.className = "min-w-0";

    const name = document.createElement("div");
    name.className = "file-manager-info-name";
    name.textContent = item.name || basename(item.path);

    const path = document.createElement("div");
    path.className = "file-manager-info-path";
    path.title = item.path || "";
    path.textContent = item.path || "";

    const details = document.createElement("dl");
    details.className = "file-manager-info-details";
    [
      ["Type", informationTypeLabel(item)],
      ["Size", item.kind === "file" ? formatSize(item.size_bytes) : "Calculated from contents"],
      ["Allocated", formatSize(item.allocated_bytes || 0)],
      ["Modified", formatDate(item.modified_at) || "-"],
      ["Accessed", formatDate(item.accessed_at) || "-"],
      ["Changed", formatDate(item.changed_at) || "-"],
      ["Permissions", item.permissions || "-"],
      ["Mode", item.mode_octal || "-"],
      ["UID:GID", item.uid === null || item.uid === undefined ? "-" : `${item.uid}:${item.gid}`],
      ["Inode", item.inode || "-"],
      ["Device", item.device || "-"],
      ["Links", item.links || "-"],
    ].forEach(([label, value]) => appendInfoDetail(details, label, value));

    if (item.error) {
      appendInfoDetail(details, "Error", item.error);
    }

    body.append(name, path, details);
    appendRichMetadata(body, item.metadata_groups, item.embedded_thumbnail_url, item);
    row.append(icon, body);
    return row;
  }

  function appendRichMetadata(container, groups, thumbnailUrl, item = {}) {
    const metadataGroups = Array.isArray(groups) ? groups : [];
    const hasVideoPreview = item.media_kind === "video";
    const videoPreviewUrl = hasVideoPreview && item.preview_url ? item.preview_url : "";
    if (!metadataGroups.length && !thumbnailUrl && !hasVideoPreview) return;
    const section = document.createElement("div");
    section.className = "file-manager-rich-metadata";
    let imageGroupBlock = null;

    metadataGroups.forEach((group) => {
      if (!group || !Array.isArray(group.fields) || !group.fields.length) return;
      const groupBlock = document.createElement("section");
      groupBlock.className = "file-manager-rich-metadata-group";
      const heading = document.createElement("h4");
      heading.textContent = group.label || "Metadata";
      if (String(group.label || "").toLowerCase() === "image") imageGroupBlock = groupBlock;
      const details = document.createElement("dl");
      details.className = "file-manager-info-details";
      group.fields.forEach((field) => {
        if (!field || field.value === null || field.value === undefined || String(field.value).trim() === "") return;
        appendInfoDetail(details, field.label || "Value", formatMetadataValue(field.label, field.value));
      });
      if (details.children.length) groupBlock.append(heading, details);
      if (groupBlock.children.length) section.appendChild(groupBlock);
    });

    if (thumbnailUrl) {
      if (!imageGroupBlock) {
        imageGroupBlock = document.createElement("section");
        imageGroupBlock.className = "file-manager-rich-metadata-group";
        const heading = document.createElement("h4");
        heading.textContent = "Image";
        imageGroupBlock.appendChild(heading);
        section.appendChild(imageGroupBlock);
      }
      const thumbnail = document.createElement("img");
      thumbnail.className = "file-manager-info-thumbnail";
      thumbnail.src = thumbnailUrl;
      thumbnail.alt = "Embedded artwork";
      thumbnail.loading = "lazy";
      imageGroupBlock.appendChild(thumbnail);
    }

    if (hasVideoPreview) {
      if (!imageGroupBlock) {
        imageGroupBlock = document.createElement("section");
        imageGroupBlock.className = "file-manager-rich-metadata-group";
        const heading = document.createElement("h4");
        heading.textContent = "Image";
        imageGroupBlock.appendChild(heading);
        section.appendChild(imageGroupBlock);
      }
      appendVideoThumbnail(imageGroupBlock, videoPreviewUrl);
    }

    if (section.children.length) container.appendChild(section);
  }

  function appendVideoThumbnail(container, url) {
    const wrapper = document.createElement("div");
    wrapper.className = "file-manager-info-video-thumbnail";
    if (!url) {
      wrapper.classList.add("is-unavailable");
      wrapper.innerHTML = '<i class="bi bi-file-earmark-play" aria-hidden="true"></i><span>Video thumbnail unavailable for this file size.</span>';
      container.appendChild(wrapper);
      return;
    }
    wrapper.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>';
    container.appendChild(wrapper);

    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    video.src = url;
    let finished = false;

    const cleanup = () => {
      video.removeAttribute("src");
      video.load();
    };
    const fail = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(timeoutId);
      wrapper.classList.add("is-unavailable");
      wrapper.innerHTML = '<i class="bi bi-file-earmark-play" aria-hidden="true"></i><span>Video thumbnail unavailable in this browser.</span>';
      cleanup();
    };
    const drawFrame = () => {
      if (finished) return;
      if (!video.videoWidth || !video.videoHeight) {
        fail();
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.className = "file-manager-info-thumbnail";
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) {
        fail();
        return;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      finished = true;
      window.clearTimeout(timeoutId);
      wrapper.replaceChildren(canvas);
      cleanup();
    };
    const timeoutId = window.setTimeout(fail, 4500);
    video.addEventListener("loadedmetadata", () => {
      if (Number.isFinite(video.duration) && video.duration > 0.2) {
        try {
          video.currentTime = Math.min(0.2, video.duration / 2);
        } catch (_) {
          drawFrame();
        }
      } else {
        drawFrame();
      }
    }, { once: true });
    video.addEventListener("seeked", drawFrame, { once: true });
    video.addEventListener("loadeddata", () => {
      if (!Number.isFinite(video.duration) || video.duration <= 0.2) drawFrame();
    }, { once: true });
    video.addEventListener("error", fail, { once: true });
  }

  function formatMetadataValue(label, value) {
    if (label !== "Duration") return value;
    const seconds = Number.parseFloat(value);
    if (!Number.isFinite(seconds) || seconds < 0) return value;
    const totalSeconds = Math.round(seconds);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainder = totalSeconds % 60;
    if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`;
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  }

  function appendInfoDetail(container, label, value) {
    const item = document.createElement("div");
    item.className = "file-manager-info-detail";
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
    item.append(term, definition);
    container.appendChild(item);
  }

  function renderInformationErrors(errors) {
    informationErrorsSection?.classList.toggle("d-none", !errors.length);
    if (!informationErrors) return;
    informationErrors.replaceChildren();
    errors.forEach((error) => {
      const item = document.createElement("div");
      item.className = "file-manager-info-error";
      item.innerHTML = `<strong></strong><span></span>`;
      item.querySelector("strong").textContent = error.path || "";
      item.querySelector("span").textContent = error.message || "Could not read this path.";
      informationErrors.appendChild(item);
    });
  }

  function informationTypeLabel(item) {
    const parts = [titleCase(item.kind || "unknown")];
    if (item.content_type) parts.push(item.content_type);
    if (item.is_symlink) parts.push("symlink");
    return parts.join(" · ");
  }

  function fileManagerFormData() {
    const formData = new FormData();
    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    formData.append("csrfmiddlewaretoken", csrfInput ? csrfInput.value : "");
    return formData;
  }

  function openCreateFolderModal() {
    activeActionTargetPath = actionTargetPath();
    if (!window.bootstrap || !createFolderModalElement) return;
    window.bootstrap.Modal.getOrCreateInstance(createFolderModalElement).show();
  }

  function actionTargetPath() {
    return contextFolderPath || currentPath || "/";
  }

  function uploadTargetPath() {
    return activeActionTargetPath || currentPath || "/";
  }

  function selectedPreviewItem() {
    if (selectedPaths.size !== 1) return null;
    const selectedPath = Array.from(selectedPaths)[0];
    return Array.from(page.querySelectorAll(".file-manager-item[data-path]")).find((item) => {
      return item.dataset.path === selectedPath && item.dataset.kind !== "folder" && Boolean(item.dataset.previewUrl);
    }) || null;
  }

  function selectedArchiveItem() {
    if (selectedPaths.size !== 1) return null;
    const selectedPath = Array.from(selectedPaths)[0];
    const element = Array.from(page.querySelectorAll(".file-manager-item[data-path]")).find((item) => {
      return !item.dataset.parentRow && item.dataset.path === selectedPath;
    });
    if (!element || element.dataset.kind === "folder") return null;
    return isSupportedArchiveName(element.dataset.name || selectedPath) ? element : null;
  }

  function isSupportedArchiveName(name) {
    return /\.(tar\.bz2|tar\.gz|tar\.xz|tbz2|tgz|txz|zip|tar)$/i.test(String(name || ""));
  }

  function updateUncompressAction(selectedCount) {
    if (!uncompressTrigger) return;
    const available = selectedCount === 1 && Boolean(selectedArchiveItem());
    uncompressTrigger.classList.toggle("d-none", !available);
    uncompressTrigger.disabled = !available;
  }

  function selectedItems() {
    return Array.from(selectedPaths).map((path) => {
      const element = Array.from(page.querySelectorAll(".file-manager-item[data-path]")).find((item) => {
        return !item.dataset.parentRow && item.dataset.path === path;
      });
      return element ? itemFromElement(element) : { path, name: basename(path), kind: "file", size_bytes: "" };
    });
  }

  function basename(path) {
    const cleanPath = String(path || "").replace(/\/+$/, "");
    return cleanPath.split("/").pop() || cleanPath || "/";
  }

  async function openPreviewModal(item) {
    if (!item || !item.dataset.previewUrl) return;
    resetPreviewModal();
    if (previewTitle) previewTitle.textContent = item.dataset.name || "File preview";
    if (window.bootstrap && previewModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(previewModalElement).show();
    }
    const mediaKind = item.dataset.mediaKind || "";
    const previewUrl = item.dataset.previewUrl;
    if (mediaKind === "image") {
      renderPreviewImage(previewUrl, item.dataset.name || "");
      return;
    }
    if (mediaKind === "video") {
      renderPreviewVideo(previewUrl, item.dataset.contentType || "video/mp4");
      return;
    }
    if (mediaKind === "audio") {
      renderPreviewAudio(previewUrl, item.dataset.contentType || "audio/mpeg");
      return;
    }
    if (mediaKind === "text") {
      await renderPreviewText(previewUrl);
      return;
    }
    setPreviewStatus("Preview is not available for this file type.", true);
  }

  function resetPreviewModal() {
    if (previewStage) {
      previewStage.innerHTML = '<div class="file-manager-empty">Select a previewable file.</div>';
    }
    setPreviewStatus("");
  }

  function renderPreviewImage(url, name) {
    if (!previewStage) return;
    previewStage.innerHTML = "";
    const image = document.createElement("img");
    image.className = "file-manager-preview-image";
    image.src = url;
    image.alt = name || "Image preview";
    previewStage.appendChild(image);
  }

  function renderPreviewVideo(url, contentType) {
    if (!previewStage) return;
    previewStage.innerHTML = '<div class="file-manager-empty"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Loading video preview...</div>';
    const video = document.createElement("video");
    video.className = "file-manager-preview-video";
    video.controls = true;
    video.preload = "metadata";
    const source = document.createElement("source");
    source.src = url;
    source.type = contentType;
    video.appendChild(source);
    let settled = false;
    const fail = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      previewStage.innerHTML = `
        <div class="file-manager-preview-unavailable">
          <i class="bi bi-file-earmark-play" aria-hidden="true"></i>
          <strong>Video preview unavailable</strong>
          <span>This browser cannot decode this video container or codec here. The file is still accessible from the file manager.</span>
        </div>
      `;
      setPreviewStatus(`Preview unavailable for ${contentType || "this video type"}.`, true);
    };
    const show = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      setPreviewStatus("", false);
      previewStage.replaceChildren(video);
    };
    const timeoutId = window.setTimeout(fail, 5500);
    video.addEventListener("loadedmetadata", show, { once: true });
    video.addEventListener("loadeddata", show, { once: true });
    video.addEventListener("canplay", show, { once: true });
    video.addEventListener("error", fail, { once: true });
    video.load();
  }

  function renderPreviewAudio(url, contentType) {
    if (!previewStage) return;
    previewStage.innerHTML = "";
    const audio = document.createElement("audio");
    audio.className = "file-manager-preview-audio";
    audio.controls = true;
    audio.preload = "metadata";
    const source = document.createElement("source");
    source.src = url;
    source.type = contentType;
    audio.appendChild(source);
    previewStage.appendChild(audio);
  }

  async function renderPreviewText(url) {
    if (!previewStage) return;
    previewStage.innerHTML = '<div class="file-manager-empty">Loading text preview...</div>';
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      previewStage.innerHTML = "";
      const block = document.createElement("pre");
      block.className = "file-manager-preview-text";
      block.textContent = text;
      previewStage.appendChild(block);
    } catch (error) {
      previewStage.innerHTML = "";
      setPreviewStatus(error.message || "Could not load text preview.", true);
    }
  }

  function setPreviewStatus(message, isError) {
    if (!previewStatus) return;
    previewStatus.textContent = message || "";
    previewStatus.classList.toggle("d-none", !message);
    previewStatus.classList.toggle("is-error", Boolean(isError));
  }

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
    items.forEach((item) => {
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

  function openUploadModal() {
    activeActionTargetPath = actionTargetPath();
    clearUploadFiles();
    setUploadStatus("");
    setUploadProgress(0, true);
    renderBreadcrumbs(uploadBreadcrumbs, uploadTargetPath(), navigateTo);
    if (window.bootstrap && uploadModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(uploadModalElement).show();
    }
  }

  function clearUploadFiles() {
    uploadFiles = [];
    if (uploadFilesInput) uploadFilesInput.value = "";
    if (uploadFolderInput) uploadFolderInput.value = "";
    renderUploadFiles();
  }

  function addUploadFiles(fileList, input) {
    const nextFiles = Array.from(fileList || []);
    const knownKeys = new Set(uploadFiles.map(uploadFileKey));
    nextFiles.forEach((file) => {
      const key = uploadFileKey(file);
      if (!knownKeys.has(key)) {
        uploadFiles.push(file);
        knownKeys.add(key);
      }
    });
    if (input) input.value = "";
    renderUploadFiles();
    setUploadStatus("");
    setUploadProgress(0, true);
  }

  function handleUploadDragEnter(event) {
    event.preventDefault();
    uploadDragDepth += 1;
    uploadDropzone?.classList.add("is-dragover");
  }

  function handleUploadDragOver(event) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    uploadDropzone?.classList.add("is-dragover");
  }

  function handleUploadDragLeave(event) {
    event.preventDefault();
    uploadDragDepth = Math.max(0, uploadDragDepth - 1);
    if (!uploadDragDepth) uploadDropzone?.classList.remove("is-dragover");
  }

  async function handleUploadDrop(event) {
    event.preventDefault();
    uploadDragDepth = 0;
    uploadDropzone?.classList.remove("is-dragover");
    const dataTransfer = event.dataTransfer;
    if (!dataTransfer) return;

    try {
      setUploadStatus("Reading dropped files and folders...");
      const entries = Array.from(dataTransfer.items || [])
        .map((item) => (typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null))
        .filter(Boolean);
      if (entries.length) {
        const files = (await Promise.all(entries.map((entry) => readUploadEntry(entry)))).flat();
        addUploadFiles(files);
      } else {
        addUploadFiles(dataTransfer.files);
      }
      setUploadStatus("");
    } catch (error) {
      setUploadStatus(error.message || "Could not read the dropped items.", true);
    }
  }

  async function readUploadEntry(entry, parentPath = "") {
    const relativePath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      Object.defineProperty(file, "uploadRelativePath", { value: relativePath, configurable: true });
      return [file];
    }
    if (!entry.isDirectory) return [];

    const entries = await readUploadDirectory(entry.createReader());
    const nestedFiles = await Promise.all(entries.map((child) => readUploadEntry(child, relativePath)));
    return nestedFiles.flat();
  }

  function readUploadDirectory(reader) {
    return new Promise((resolve, reject) => {
      const entries = [];
      const readBatch = () => reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries);
          return;
        }
        entries.push(...batch);
        readBatch();
      }, reject);
      readBatch();
    });
  }

  function renderUploadFiles() {
    const groups = groupedUploadFiles();
    if (uploadSelection) {
      const totalBytes = uploadFiles.reduce((total, file) => total + file.size, 0);
      uploadSelection.textContent = groups.length
        ? `${groups.length} selected item${groups.length === 1 ? "" : "s"} · ${uploadFiles.length} file${uploadFiles.length === 1 ? "" : "s"} · ${formatSize(totalBytes)}`
        : "No files selected.";
    }
    if (uploadStart) uploadStart.disabled = uploadFiles.length === 0;
    if (uploadClearButton) uploadClearButton.disabled = uploadFiles.length === 0;
    if (!uploadList) return;

    uploadList.replaceChildren();
    uploadList.classList.toggle("d-none", uploadFiles.length === 0);
    groups.slice(0, 30).forEach((group) => {
      const item = document.createElement("div");
      item.className = "file-manager-upload-item";

      const name = document.createElement("div");
      name.className = "file-manager-upload-name";
      name.title = group.label;
      name.textContent = group.label;

      const meta = document.createElement("div");
      meta.className = "text-secondary small";
      meta.textContent = group.kind === "folder"
        ? `${group.count} file${group.count === 1 ? "" : "s"} · ${formatSize(group.size)}`
        : formatSize(group.size);

      item.append(name, meta);
      uploadList.appendChild(item);
    });

    if (groups.length > 30) {
      const more = document.createElement("div");
      more.className = "file-manager-upload-more small";
      more.textContent = `${groups.length - 30} more selected item${groups.length - 30 === 1 ? "" : "s"}`;
      uploadList.appendChild(more);
    }
  }

  function groupedUploadFiles() {
    const groups = new Map();
    uploadFiles.forEach((file) => {
      const relativeName = uploadFileName(file);
      const slashIndex = relativeName.indexOf("/");
      const isFolderEntry = Boolean(file.webkitRelativePath) && slashIndex > 0;
      const label = isFolderEntry ? `${relativeName.slice(0, slashIndex)}/` : relativeName;
      const key = `${isFolderEntry ? "folder" : "file"}:${label}`;
      const existing = groups.get(key) || {
        label,
        kind: isFolderEntry ? "folder" : "file",
        count: 0,
        size: 0
      };
      existing.count += 1;
      existing.size += file.size;
      groups.set(key, existing);
    });
    return Array.from(groups.values());
  }

  function uploadFileName(file) {
    return file.uploadRelativePath || file.webkitRelativePath || file.name;
  }

  function uploadFileKey(file) {
    return `${uploadFileName(file)}::${file.size}::${file.lastModified}`;
  }

  async function startUpload() {
    if (uploadChunkToggle && !uploadChunkToggle.checked) {
      startDirectUpload();
      return;
    }
    const targetPath = uploadTargetPath();
    const totalBytes = uploadFiles.reduce((total, file) => total + file.size, 0);
    let uploadedBytes = 0;
    if (uploadStart) uploadStart.disabled = true;
    setUploadStatus("Starting upload process...");
    setUploadProgress(0, false);

    try {
      const startPayload = await postUploadForm({
        file_action: "upload_start",
        current_path: targetPath,
        return_path: currentPath,
        upload_workers: uploadWorkers ? uploadWorkers.value : "2",
        file_count: String(uploadFiles.length)
      });

      for (const file of uploadFiles) {
        const totalChunks = Math.max(1, Math.ceil(file.size / uploadChunkSize));
        for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
          const start = chunkIndex * uploadChunkSize;
          const end = Math.min(file.size, start + uploadChunkSize);
          const chunk = file.slice(start, end);
          setUploadStatus(`Uploading ${uploadFileName(file)} (${chunkIndex + 1}/${totalChunks})...`);
          await postUploadChunk(targetPath, startPayload.operation_id, file, chunk, chunkIndex, totalChunks);
          uploadedBytes += chunk.size;
          setUploadProgress(totalBytes ? Math.round((uploadedBytes / totalBytes) * 100) : 100, false);
        }
      }

      const finishPayload = await postUploadForm({
        file_action: "upload_finish",
        current_path: targetPath,
        return_path: currentPath,
        operation_id: String(startPayload.operation_id)
      });
      setUploadProgress(100, false);
      setUploadStatus(finishPayload.summary || "Upload complete.");
      window.location.href = finishPayload.detail_url;
    } catch (error) {
      setUploadStatus(error.message || "Upload failed.", true);
      if (uploadStart) uploadStart.disabled = uploadFiles.length === 0;
    }
  }

  function startDirectUpload() {
    const targetPath = uploadTargetPath();
    const formData = new FormData();
    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    formData.append("csrfmiddlewaretoken", csrfInput ? csrfInput.value : "");
    formData.append("file_action", "upload");
    formData.append("current_path", targetPath);
    formData.append("return_path", currentPath);
    formData.append("upload_workers", uploadWorkers ? uploadWorkers.value : "2");
    uploadFiles.forEach((file) => {
      formData.append("uploads", file, uploadFileName(file));
    });

    const xhr = new XMLHttpRequest();
    xhr.open("POST", window.location.pathname + window.location.search);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      setUploadProgress(Math.round((event.loaded / event.total) * 100), false);
    });
    xhr.addEventListener("load", () => {
      try {
        const payload = JSON.parse(xhr.responseText || "{}");
        if (xhr.status >= 200 && xhr.status < 300 && payload.detail_url) {
          setUploadProgress(100, false);
          setUploadStatus(payload.summary || "Upload complete.");
          window.location.href = payload.detail_url;
          return;
        }
        setUploadStatus(payload.error || payload.summary || `Upload failed with HTTP ${xhr.status}`, true);
      } catch (error) {
        setUploadStatus(`Upload failed with HTTP ${xhr.status}`, true);
      }
      if (uploadStart) uploadStart.disabled = uploadFiles.length === 0;
    });
    xhr.addEventListener("error", () => {
      setUploadStatus("Upload failed due to a network error.", true);
      if (uploadStart) uploadStart.disabled = uploadFiles.length === 0;
    });
    setUploadStatus("Uploading files in a single request...");
    setUploadProgress(0, false);
    if (uploadStart) uploadStart.disabled = true;
    xhr.send(formData);
  }

  function postUploadChunk(targetPath, operationId, file, chunk, chunkIndex, totalChunks) {
    const formData = new FormData();
    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    formData.append("csrfmiddlewaretoken", csrfInput ? csrfInput.value : "");
    formData.append("file_action", "upload_chunk");
    formData.append("current_path", targetPath);
    formData.append("return_path", currentPath);
    formData.append("operation_id", String(operationId));
    formData.append("relative_path", uploadFileName(file));
    formData.append("chunk_index", String(chunkIndex));
    formData.append("total_chunks", String(totalChunks));
    formData.append("chunk", chunk, uploadFileName(file));
    return postUploadRequest(formData);
  }

  function postUploadForm(fields) {
    const formData = new FormData();
    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    formData.append("csrfmiddlewaretoken", csrfInput ? csrfInput.value : "");
    Object.entries(fields).forEach(([key, value]) => formData.append(key, value));
    return postUploadRequest(formData);
  }

  function postUploadRequest(formData) {
    const xhr = new XMLHttpRequest();
    return new Promise((resolve, reject) => {
      xhr.open("POST", window.location.pathname + window.location.search);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.addEventListener("load", () => {
        try {
          const payload = JSON.parse(xhr.responseText || "{}");
          if (xhr.status >= 200 && xhr.status < 300 && payload.ok !== false) {
            resolve(payload);
            return;
          }
          reject(new Error(payload.error || payload.summary || `Upload failed with HTTP ${xhr.status}`));
        } catch (error) {
          reject(new Error(`Upload failed with HTTP ${xhr.status}`));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("Upload failed due to a network error.")));
      xhr.send(formData);
    });
  }

  function setUploadProgress(percent, hidden) {
    if (uploadProgressWrap) uploadProgressWrap.classList.toggle("d-none", Boolean(hidden));
    if (uploadProgressBar) {
      uploadProgressBar.style.width = `${percent}%`;
      uploadProgressBar.textContent = `${percent}%`;
    }
  }

  function setUploadStatus(message, isError) {
    if (!uploadStatus) return;
    uploadStatus.textContent = message || "";
    uploadStatus.classList.toggle("d-none", !message);
    uploadStatus.classList.toggle("is-error", Boolean(isError));
  }

  function startDownloadPreparation() {
    if (!selectedPaths.size) return;
    resetDownloadModal();
    if (downloadSelection) {
      downloadSelection.textContent = `${selectedPaths.size} item${selectedPaths.size === 1 ? "" : "s"} selected.`;
    }
    if (window.bootstrap && downloadModalElement) {
      window.bootstrap.Modal.getOrCreateInstance(downloadModalElement).show();
    }

    const formData = new FormData();
    const csrfInput = page.querySelector("input[name='csrfmiddlewaretoken']");
    formData.append("csrfmiddlewaretoken", csrfInput ? csrfInput.value : "");
    formData.append("file_action", "download");
    formData.append("current_path", currentPath);
    formData.append("return_path", currentPath);
    selectedPaths.forEach((path) => formData.append("selected_paths", path));

    fetch(window.location.pathname + window.location.search, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: formData
    })
      .then((response) => response.json().then((payload) => ({ response, payload })))
      .then(({ response, payload }) => {
        if (!response.ok || !payload.status_url) {
          throw new Error(payload.error || payload.summary || `HTTP ${response.status}`);
        }
        if (downloadDetail) {
          downloadDetail.href = payload.detail_url || "#";
          downloadDetail.classList.remove("disabled");
        }
        setDownloadStatus(payload.summary || "Download archive preparation started.");
        pollDownloadStatus(payload.status_url);
        downloadPollTimer = window.setInterval(() => pollDownloadStatus(payload.status_url), 2000);
      })
      .catch((error) => {
        setDownloadStatus(error.message || "Could not start download preparation.", true);
      });
  }

  function resetDownloadModal() {
    if (downloadPollTimer) {
      window.clearInterval(downloadPollTimer);
      downloadPollTimer = null;
    }
    setDownloadProgress(0);
    setDownloadStatus("Starting download preparation...");
    if (downloadLog) {
      downloadLog.textContent = "";
      downloadLog.classList.add("d-none");
    }
    if (downloadReady) {
      downloadReady.href = "#";
      downloadReady.classList.add("disabled");
    }
    downloadAutoStarted = false;
    if (downloadDetail) {
      downloadDetail.href = "#";
      downloadDetail.classList.add("disabled");
    }
  }

  async function pollDownloadStatus(statusUrl) {
    try {
      const response = await fetch(statusUrl, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" }
      });
      if (!response.ok) return;
      const payload = await response.json();
      setDownloadProgress(payload.progress_percent || 0);
      setDownloadStatus(payload.summary || payload.status_label || "Preparing archive.", payload.status === "failed");
      if (downloadLog) {
        downloadLog.textContent = payload.log_output || "";
        downloadLog.classList.toggle("d-none", !payload.log_output);
        downloadLog.scrollTop = downloadLog.scrollHeight;
      }
      if (payload.status === "success" && payload.download_url) {
        setDownloadProgress(100);
        setDownloadStatus("Download archive ready. Starting browser download...");
        if (downloadReady) {
          downloadReady.href = payload.download_url;
          downloadReady.classList.remove("disabled");
        }
        triggerBrowserDownload(payload.download_url);
        if (downloadPollTimer) {
          window.clearInterval(downloadPollTimer);
          downloadPollTimer = null;
        }
      }
      if (["failed", "cancelled"].includes(payload.status) && downloadPollTimer) {
        window.clearInterval(downloadPollTimer);
        downloadPollTimer = null;
      }
    } catch (_) {
    }
  }

  function setDownloadProgress(percent) {
    const bounded = Math.max(0, Math.min(Number(percent) || 0, 100));
    if (downloadProgressBar) {
      downloadProgressBar.style.width = `${bounded}%`;
      downloadProgressBar.textContent = `${bounded}%`;
    }
  }

  function setDownloadStatus(message, isError) {
    if (!downloadStatus) return;
    downloadStatus.textContent = message || "";
    downloadStatus.classList.toggle("is-error", Boolean(isError));
  }

  function triggerBrowserDownload(url) {
    if (!url || downloadAutoStarted) return;
    downloadAutoStarted = true;
    const frame = document.createElement("iframe");
    frame.src = url;
    frame.className = "d-none";
    frame.setAttribute("aria-hidden", "true");
    document.body.appendChild(frame);
    window.setTimeout(() => frame.remove(), 120000);
  }

  async function loadDestination(path, { updateHistory = true } = {}) {
    if (!destinationRows) return;
    destinationModalElement?.setAttribute("aria-busy", "true");
    if (destinationSubmit) destinationSubmit.disabled = true;
    destinationLoading?.classList.remove("d-none");
    destinationRows.innerHTML = '<div class="file-manager-empty"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Loading folders...</div>';
    try {
      const url = new URL(listUrl, window.location.origin);
      url.searchParams.set("path", path || "/");
      url.searchParams.set("folders_only", "1");
      url.searchParams.set("sort", destinationSort.field);
      url.searchParams.set("direction", destinationSort.direction);
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" }
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      destinationPath = payload.path || "/";
      if (destinationSortField) destinationSortField.value = payload.sort_field || destinationSort.field;
      destinationParentPath = payload.parent_path || "";
      if (destinationPathInput) destinationPathInput.value = destinationPath;
      renderBreadcrumbs(destinationBreadcrumbs, destinationPath, loadDestination);
      if (destinationUp) destinationUp.disabled = !destinationParentPath;
      renderDestinationRows(payload.items || []);
      if (updateHistory) {
        window.history.pushState({ fileManagerDestinationPath: destinationPath }, "", window.location.href);
      }
    } catch (error) {
      destinationRows.innerHTML = `<div class="file-manager-status">${escapeHtml(error.message || "Could not load folders.")}</div>`;
    } finally {
      destinationModalElement?.setAttribute("aria-busy", "false");
      destinationLoading?.classList.add("d-none");
      if (destinationSubmit) destinationSubmit.disabled = false;
    }
  }

  function renderDestinationRows(items) {
    destinationRows.innerHTML = "";
    if (destinationParentPath) {
      const upRow = document.createElement("button");
      upRow.type = "button";
      upRow.className = "file-manager-destination-row file-manager-parent-row";
      upRow.innerHTML = '<i class="bi bi-arrow-up-short"></i><span class="text-truncate">..</span>';
      upRow.addEventListener("click", () => loadDestination(destinationParentPath));
      destinationRows.appendChild(upRow);
    }
    if (!items.length) {
      if (!destinationParentPath) {
        destinationRows.innerHTML = '<div class="file-manager-empty">No child folders.</div>';
      }
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "file-manager-destination-row";
      row.innerHTML = '<i class="bi bi-folder-fill"></i><span class="text-truncate"></span>';
      row.querySelector("span").textContent = item.name || "";
      row.addEventListener("click", () => loadDestination(item.path));
      destinationRows.appendChild(row);
    });
  }

  function renderBreadcrumbs(container, path, onNavigate) {
    if (!container) return;
    container.innerHTML = "";
    const parts = breadcrumbParts(path);
    parts.forEach((part, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `file-manager-breadcrumb${index === parts.length - 1 ? " is-current" : ""}`;
      button.textContent = part.label;
      button.title = part.path;
      button.addEventListener("click", () => onNavigate(part.path));
      container.appendChild(button);
      if (index < parts.length - 1) {
        const separator = document.createElement("span");
        separator.className = "file-manager-breadcrumb-separator";
        separator.textContent = "/";
        container.appendChild(separator);
      }
    });
  }

  function breadcrumbParts(path) {
    const normalized = path && path.startsWith("/") ? path : "/";
    if (normalized === "/") return [{ label: "/", path: "/" }];
    const parts = [{ label: "/", path: "/" }];
    let current = "";
    normalized.split("/").filter(Boolean).forEach((part) => {
      current += `/${part}`;
      parts.push({ label: part, path: current });
    });
    return parts;
  }

  function ownerLabel(item) {
    if (!item.owner && !item.group) return "-";
    return item.group ? `${item.owner || "-"}:${item.group}` : item.owner;
  }

  function setError(message) {
    if (!errorBox) return;
    errorBox.textContent = message || "";
    errorBox.classList.toggle("d-none", !message);
  }

  function formatVisibleValues() {
    page.querySelectorAll("[data-file-date]").forEach((node) => {
      node.textContent = formatDate(node.dataset.fileDate) || "-";
    });
    page.querySelectorAll("[data-size-bytes]").forEach((node) => {
      node.textContent = formatSize(node.dataset.sizeBytes);
    });
  }

  function formatDate(value) {
    if (!value) return "";
    if (window.formatConfiguredDateTime) {
      return window.formatConfiguredDateTime(value, "datetime-short");
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
  }

  function formatSize(value) {
    if (value === null || value === undefined || value === "") return "-";
    const bytes = Number(value);
    if (!Number.isFinite(bytes)) return "-";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB", "PB"];
    let size = bytes / 1024;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
  }

  function titleCase(value) {
    const text = String(value || "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }
})();
