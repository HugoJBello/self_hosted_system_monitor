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
  const columnResizers = page.querySelectorAll("[data-column-resize]");
  const fileSearchLink = page.querySelector("[data-file-search-link]");
  const parentButton = page.querySelector("[data-parent-button]");
  const viewModeToggle = page.querySelector("[data-view-mode-toggle]");
  const viewModeLabel = page.querySelector("[data-view-mode-label]");
  const multipleSelectToggle = page.querySelector("[data-multiple-select-toggle]");
  const singleClickToggle = page.querySelector("[data-single-click-toggle]");
  const selectAllToggle = page.querySelector("[data-select-all-toggle]");
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
  const pdfTocToggle = page.querySelector("[data-pdf-toc-toggle]");
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
  let hasSingleClickOpenPreference = false;
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
  const pdfJsVersion = "6.3.289";
  const pdfJsModuleUrl = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfJsVersion}/build/pdf.mjs`;
  const pdfJsWorkerUrl = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfJsVersion}/build/pdf.worker.mjs`;
  let informationPollTimer = null;
  let pdfJsLibraryPromise = null;
  let previewRenderId = 0;
  const preferenceKeys = {
    viewMode: "fileManager.viewMode",
    multipleSelect: "fileManager.multipleSelect",
    singleClickOpen: "fileManager.singleClickOpen",
    sortField: "fileManager.sortField",
    sortDirection: "fileManager.sortDirection",
    columnWidths: "fileManager.columnWidths"
  };
  const resizableColumns = {
    name: { min: 180, max: 1200 },
    kind: { min: 80, max: 320 },
    size: { min: 90, max: 360 },
    modified: { min: 150, max: 440 },
    owner: { min: 120, max: 420 },
    permissions: { min: 120, max: 360 },
  };

  page.dataset.previousPath = currentPath;
  formatVisibleValues();
  renderBreadcrumbs(currentBreadcrumbs, currentPath, navigateTo);
  window.history.replaceState({ ...(window.history.state || {}), fileManagerPath: currentPath }, "", window.location.href);
  restoreColumnWidths();
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
  columnResizers.forEach((handle) => {
    handle.addEventListener("pointerdown", startColumnResize);
    handle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  });
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
  pdfTocToggle?.addEventListener("click", togglePdfToc);

  multipleSelectToggle?.addEventListener("click", () => {
    setMultipleSelectEnabled(!multipleSelectEnabled);
  });
  singleClickToggle?.addEventListener("click", () => {
    setSingleClickOpenEnabled(!singleClickOpenEnabled);
  });
  selectAllToggle?.addEventListener("click", toggleSelectAllVisibleItems);
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
