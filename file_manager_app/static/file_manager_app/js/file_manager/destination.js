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
      bindDestinationOpen(upRow, () => loadDestination(destinationParentPath));
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
      bindDestinationOpen(row, () => loadDestination(item.path));
      destinationRows.appendChild(row);
    });
  }

  function bindDestinationOpen(row, openHandler) {
    row.addEventListener("click", () => {
      if (destinationUsesSingleClickOpen()) openHandler();
    });
    row.addEventListener("dblclick", () => {
      if (!destinationUsesSingleClickOpen()) openHandler();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        openHandler();
      }
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
