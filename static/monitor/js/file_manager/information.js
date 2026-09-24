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
