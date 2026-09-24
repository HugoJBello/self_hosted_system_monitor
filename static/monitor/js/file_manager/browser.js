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

  function startColumnResize(event) {
    const column = event.currentTarget?.dataset?.columnResize || "";
    const limits = resizableColumns[column];
    const header = event.currentTarget?.closest("[data-sort-header]");
    if (!limits || !header) return;
    event.preventDefault();
    event.stopPropagation();

    const startX = event.clientX;
    const startWidth = header.getBoundingClientRect().width;
    page.classList.add("is-resizing-column");
    event.currentTarget.setPointerCapture?.(event.pointerId);

    const move = (moveEvent) => {
      const nextWidth = Math.min(Math.max(startWidth + moveEvent.clientX - startX, limits.min), limits.max);
      setColumnWidth(column, nextWidth);
    };
    const stop = () => {
      page.classList.remove("is-resizing-column");
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", stop);
      document.removeEventListener("pointercancel", stop);
      saveColumnWidths();
    };

    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", stop);
    document.addEventListener("pointercancel", stop);
  }

  function setColumnWidth(column, width) {
    if (!resizableColumns[column]) return;
    page.style.setProperty(`--file-manager-col-${column}`, `${Math.round(width)}px`);
  }

  function currentColumnWidths() {
    return Object.keys(resizableColumns).reduce((widths, column) => {
      const value = page.style.getPropertyValue(`--file-manager-col-${column}`).trim();
      const width = Number.parseInt(value, 10);
      if (Number.isFinite(width)) widths[column] = width;
      return widths;
    }, {});
  }

  function saveColumnWidths() {
    try {
      window.sessionStorage.setItem(preferenceKeys.columnWidths, JSON.stringify(currentColumnWidths()));
    } catch (_) {
    }
  }

  function restoreColumnWidths() {
    let widths = {};
    try {
      widths = JSON.parse(window.sessionStorage.getItem(preferenceKeys.columnWidths) || "{}");
    } catch (_) {
      widths = {};
    }
    Object.entries(widths || {}).forEach(([column, width]) => {
      const limits = resizableColumns[column];
      const numericWidth = Number(width);
      if (!limits || !Number.isFinite(numericWidth)) return;
      setColumnWidth(column, Math.min(Math.max(numericWidth, limits.min), limits.max));
    });
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

  function setSingleClickOpenEnabled(enabled, { save = true } = {}) {
    singleClickOpenEnabled = Boolean(enabled);
    page.classList.toggle("is-single-click-open", singleClickOpenEnabled);
    singleClickToggle?.setAttribute("aria-pressed", singleClickOpenEnabled ? "true" : "false");
    singleClickToggle?.classList.toggle("active", singleClickOpenEnabled);
    if (singleClickOpenEnabled && !multipleSelectEnabled) clearSelection();
    if (save) {
      hasSingleClickOpenPreference = true;
      saveSessionPreference(preferenceKeys.singleClickOpen, singleClickOpenEnabled ? "1" : "0");
    }
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
    const storedSingleClickOpen = loadSessionPreference(preferenceKeys.singleClickOpen);
    hasSingleClickOpenPreference = storedSingleClickOpen !== null;
    setSingleClickOpenEnabled(storedSingleClickOpen === "1", { save: false });
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

  function selectableCurrentPaths() {
    return Array.from(page.querySelectorAll(`${viewMode === "grid" ? "[data-file-manager-grid]" : "[data-file-manager-rows]"} .file-manager-item[data-path]`))
      .filter((item) => !item.dataset.parentRow)
      .map((item) => item.dataset.path || "")
      .filter(Boolean);
  }

  function toggleSelectAllVisibleItems() {
    const paths = selectableCurrentPaths();
    if (!paths.length) return;
    const allSelected = paths.every((path) => selectedPaths.has(path));
    if (allSelected) {
      paths.forEach((path) => selectedPaths.delete(path));
    } else {
      paths.forEach((path) => selectedPaths.add(path));
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
    updateSelectAllToggle();
    updateUncompressAction(selectedCount);
    if (selectionCount) {
      selectionCount.textContent = selectedCount ? `${selectedCount} selected` : "";
      selectionCount.classList.toggle("d-none", !multipleSelectEnabled && selectedCount < 2);
    }
    if (previewTrigger) {
      previewTrigger.disabled = !selectedPreviewItem();
    }
  }

  function updateSelectAllToggle() {
    if (!selectAllToggle) return;
    const paths = selectableCurrentPaths();
    const hasSelectableItems = paths.length > 0;
    const allSelected = hasSelectableItems && paths.every((path) => selectedPaths.has(path));
    selectAllToggle.classList.toggle("d-none", !multipleSelectEnabled);
    selectAllToggle.disabled = !multipleSelectEnabled || !hasSelectableItems;
    selectAllToggle.setAttribute("aria-pressed", allSelected ? "true" : "false");
    const label = selectAllToggle.querySelector("span");
    if (label) label.textContent = allSelected ? "Clear all" : "Select all";
    const icon = selectAllToggle.querySelector("i");
    if (icon) icon.className = `bi ${allSelected ? "bi-x-square" : "bi-check2-all"}`;
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
