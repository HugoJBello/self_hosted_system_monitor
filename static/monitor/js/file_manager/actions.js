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
