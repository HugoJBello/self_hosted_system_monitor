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
    if (mediaKind === "pdf") {
      renderPreviewPdf(previewUrl, item.dataset.name || "PDF preview");
      return;
    }
    if (mediaKind === "text") {
      await renderPreviewText(previewUrl);
      return;
    }
    setPreviewStatus("Preview is not available for this file type.", true);
  }

  function resetPreviewModal() {
    previewRenderId += 1;
    setPdfTocAvailable(false);
    if (previewStage) {
      previewStage.classList.remove("is-pdf-preview");
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
    const renderId = previewRenderId;
    previewStage.innerHTML = "";
    setPreviewStatus("Loading video metadata...", false);
    const wrapper = document.createElement("div");
    wrapper.className = "file-manager-video-preview";
    const video = document.createElement("video");
    video.className = "file-manager-preview-video";
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    video.src = url;
    const actions = document.createElement("div");
    actions.className = "file-manager-video-actions";
    const preparation = document.createElement("div");
    preparation.className = "file-manager-video-preparation d-none";
    preparation.innerHTML = `
      <div class="file-manager-video-preparation-heading">
        <i class="bi bi-gear-wide-connected" aria-hidden="true"></i>
        <div><strong data-video-preparation-title>Preparing compatible preview</strong><span data-video-preparation-detail></span></div>
      </div>
      <div class="progress" role="progressbar" aria-label="Compatible preview progress" aria-valuemin="0" aria-valuemax="100">
        <div class="progress-bar" data-video-preparation-bar></div>
      </div>
      <small data-video-preparation-help>The player will switch to the compatible version automatically when it is ready. You can close this window; preparation continues in the background.</small>
      <button type="button" class="btn btn-sm btn-primary d-none mt-2" data-video-compatible-play><i class="bi bi-play-fill me-1"></i>Play compatible preview</button>`;
    const download = document.createElement("a");
    download.className = "file-manager-video-download";
    download.href = directDownloadUrl(url);
    download.download = "";
    download.title = "Download video";
    download.setAttribute("aria-label", "Download video");
    download.innerHTML = '<i class="bi bi-download" aria-hidden="true"></i><span>Download</span>';
    actions.appendChild(download);
    wrapper.append(video, preparation, actions);
    previewStage.appendChild(wrapper);
    let loaded = false;
    const timeoutId = window.setTimeout(() => {
      if (loaded || renderId !== previewRenderId) return;
      setPreviewStatus("Video metadata is taking longer than expected. Direct download is available.", false);
    }, 12000);
    const show = () => {
      if (renderId !== previewRenderId) return;
      loaded = true;
      window.clearTimeout(timeoutId);
      if (video.currentSrc === new URL(url, window.location.href).href) setPreviewStatus("", false);
    };
    const unavailable = (message) => {
      if (renderId !== previewRenderId) return;
      window.clearTimeout(timeoutId);
      renderPreviewUnavailable({
        icon: "bi-file-earmark-play",
        title: "Video preview unavailable",
        message,
        actionUrl: directDownloadUrl(url),
        actionLabel: "Download video",
      });
      setPreviewStatus(`Preview unavailable for ${contentType || "this video type"}.`, true);
    };
    const setPreparation = (state) => {
      const visible = state?.status === "preparing";
      preparation.classList.toggle("d-none", !visible);
      if (!visible) return;
      const percent = Number(state.progress_percent || 0);
      const title = preparation.querySelector("[data-video-preparation-title]");
      const detail = preparation.querySelector("[data-video-preparation-detail]");
      const bar = preparation.querySelector("[data-video-preparation-bar]");
      const help = preparation.querySelector("[data-video-preparation-help]");
      const playButton = preparation.querySelector("[data-video-compatible-play]");
      const stage = state.stage === "remuxing" ? "Optimizing container" : state.stage === "transcoding" ? "Converting video" : "Preparing subtitles";
      title.textContent = stage;
      const eta = formatVideoEta(state.eta_seconds);
      detail.textContent = percent > 0 ? `${percent}%${eta ? ` · ${eta} remaining` : ""}${state.speed ? ` · ${state.speed}` : ""}` : "Starting…";
      bar.style.width = `${percent}%`;
      bar.parentElement.setAttribute("aria-valuenow", String(percent));
      bar.classList.toggle("progress-bar-striped", percent === 0);
      bar.classList.toggle("progress-bar-animated", percent === 0);
      help.textContent = "The player will switch to the compatible version automatically when it is ready. You can close this window; preparation continues in the background.";
      playButton.classList.add("d-none");
    };
    const setCompatibleReady = (play) => {
      preparation.classList.remove("d-none");
      preparation.querySelector("[data-video-preparation-title]").textContent = "Compatible preview ready";
      preparation.querySelector("[data-video-preparation-detail]").textContent = "The converted video is loaded in the player.";
      const bar = preparation.querySelector("[data-video-preparation-bar]");
      bar.style.width = "100%";
      bar.classList.remove("progress-bar-striped", "progress-bar-animated");
      bar.parentElement.setAttribute("aria-valuenow", "100");
      preparation.querySelector("[data-video-preparation-help]").textContent = "Press play to start. Subtitles will appear in the player menu as they become available.";
      const playButton = preparation.querySelector("[data-video-compatible-play]");
      playButton.classList.remove("d-none");
      playButton.onclick = play;
    };
    enhanceVideoPreview(video, url, contentType, {
      isCurrent: () => renderId === previewRenderId,
      setStatus: setPreviewStatus,
      unavailable,
      setPreparation,
      setCompatibleReady,
    });
    video.addEventListener("loadedmetadata", show, { once: true });
    video.addEventListener("loadeddata", show, { once: true });
    video.addEventListener("canplay", show, { once: true });
    video.load();
  }

  function formatVideoEta(seconds) {
    if (!Number.isFinite(Number(seconds)) || Number(seconds) < 0) return "";
    const total = Math.round(Number(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m`;
    return `${Math.max(1, total)}s`;
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

  async function renderPreviewPdf(url, title) {
    if (!previewStage) return;
    const renderId = previewRenderId;
    previewStage.classList.add("is-pdf-preview");
    previewStage.innerHTML = '<div class="file-manager-empty"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Loading PDF...</div>';
    try {
      const pdfjsLib = await loadPdfJs();
      if (renderId !== previewRenderId) return;
      const loadingTask = pdfjsLib.getDocument({ url, withCredentials: true });
      const pdf = await loadingTask.promise;
      if (renderId !== previewRenderId) return;

      const shell = document.createElement("div");
      shell.className = "file-manager-pdf-shell";
      const toc = document.createElement("aside");
      toc.className = "file-manager-pdf-toc";
      toc.setAttribute("aria-label", "PDF table of contents");
      const viewer = document.createElement("div");
      viewer.className = "file-manager-pdf-viewer";
      shell.append(toc, viewer);
      previewStage.replaceChildren(shell);
      const pageFrames = new Map();
      renderPdfOutline(pdf, toc, viewer, pageFrames, renderId);
      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        if (renderId !== previewRenderId) return;
        setPreviewStatus(`Rendering PDF page ${pageNumber} of ${pdf.numPages}...`, false);
        await renderPdfPage(pdf, pageNumber, viewer, pageFrames, renderId);
      }
      if (renderId === previewRenderId) setPreviewStatus("");
    } catch (error) {
      if (renderId !== previewRenderId) return;
      renderPdfFallback(url, title, error);
    }
  }

  function loadPdfJs() {
    if (!pdfJsLibraryPromise) {
      pdfJsLibraryPromise = import(pdfJsModuleUrl).then((module) => {
        const pdfjsLib = module.pdfjsLib || module;
        pdfjsLib.GlobalWorkerOptions.workerSrc = pdfJsWorkerUrl;
        return pdfjsLib;
      });
    }
    return pdfJsLibraryPromise;
  }

  async function renderPdfOutline(pdf, toc, viewer, pageFrames, renderId) {
    try {
      const outline = await pdf.getOutline();
      if (renderId !== previewRenderId) return;
      const items = await outlineItemsWithPages(pdf, outline || []);
      if (renderId !== previewRenderId) return;
      renderPdfToc(toc, items, viewer, pageFrames);
      setPdfTocAvailable(items.length > 0);
    } catch (_) {
      if (renderId === previewRenderId) setPdfTocAvailable(false);
    }
  }

  async function outlineItemsWithPages(pdf, outline, level = 0) {
    const items = [];
    for (const item of outline || []) {
      const pageNumber = await outlineItemPageNumber(pdf, item);
      items.push({
        title: item.title || "Untitled",
        pageNumber,
        level,
      });
      const children = await outlineItemsWithPages(pdf, item.items || [], level + 1);
      items.push(...children);
    }
    return items;
  }

  async function outlineItemPageNumber(pdf, item) {
    try {
      const destination = typeof item.dest === "string" ? await pdf.getDestination(item.dest) : item.dest;
      const pageReference = Array.isArray(destination) ? destination[0] : null;
      if (Number.isInteger(pageReference)) return pageReference + 1;
      if (!pageReference) return null;
      return (await pdf.getPageIndex(pageReference)) + 1;
    } catch (_) {
      return null;
    }
  }

  function renderPdfToc(toc, items, viewer, pageFrames) {
    toc.replaceChildren();
    if (!items.length) return;
    const heading = document.createElement("div");
    heading.className = "file-manager-pdf-toc-heading";
    heading.textContent = "Contents";
    toc.appendChild(heading);
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-manager-pdf-toc-item";
      button.style.setProperty("--pdf-toc-indent", `${Math.min(item.level, 4) * 0.85}rem`);
      button.disabled = !item.pageNumber;
      button.innerHTML = '<span></span><small></small>';
      button.querySelector("span").textContent = item.title;
      button.querySelector("small").textContent = item.pageNumber ? String(item.pageNumber) : "-";
      button.addEventListener("click", () => scrollPdfToPage(viewer, pageFrames, item.pageNumber));
      toc.appendChild(button);
    });
  }

  function scrollPdfToPage(viewer, pageFrames, pageNumber) {
    const pageFrame = pageFrames.get(pageNumber);
    if (!viewer || !pageFrame) return;
    viewer.scrollTo({ top: pageFrame.offsetTop - viewer.offsetTop, behavior: "smooth" });
    previewStage?.querySelector(".file-manager-pdf-shell")?.classList.remove("is-toc-open");
    pdfTocToggle?.setAttribute("aria-expanded", "false");
  }

  function setPdfTocAvailable(available) {
    if (!pdfTocToggle) return;
    pdfTocToggle.classList.toggle("d-none", !available);
    pdfTocToggle.disabled = !available;
    pdfTocToggle.setAttribute("aria-expanded", "false");
  }

  function togglePdfToc() {
    const shell = previewStage?.querySelector(".file-manager-pdf-shell");
    if (!shell || !pdfTocToggle) return;
    const open = !shell.classList.contains("is-toc-open");
    shell.classList.toggle("is-toc-open", open);
    pdfTocToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  async function renderPdfPage(pdf, pageNumber, viewer, pageFrames, renderId) {
    const page = await pdf.getPage(pageNumber);
    if (renderId !== previewRenderId) return;
    const baseViewport = page.getViewport({ scale: 1 });
    const availableWidth = Math.min(980, Math.max(280, (previewStage?.clientWidth || 640) - 32));
    const viewport = page.getViewport({ scale: availableWidth / baseViewport.width });
    const outputScale = Math.min(window.devicePixelRatio || 1, 2);

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas is not available.");
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;

    const pageFrame = document.createElement("div");
    pageFrame.className = "file-manager-pdf-page";
    pageFrame.appendChild(canvas);
    pageFrames.set(pageNumber, pageFrame);
    viewer.appendChild(pageFrame);

    await page.render({
      canvasContext: context,
      transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null,
      viewport,
    }).promise;
  }

  function renderPdfFallback(url, title, error) {
    renderPreviewUnavailable({
      icon: "bi-file-earmark-pdf",
      title: "PDF preview unavailable",
      message: error?.message || "This browser could not render the PDF preview.",
      actionUrl: directDownloadUrl(url),
      actionLabel: "Download PDF",
    });
    const link = previewStage.querySelector("a");
    if (link) link.title = title || "Download PDF";
    setPreviewStatus("", false);
  }

  function renderPreviewUnavailable({ icon, title, message, actionUrl = "", actionLabel = "" }) {
    if (!previewStage) return;
    previewStage.classList.remove("is-pdf-preview");
    previewStage.innerHTML = `
      <div class="file-manager-preview-unavailable">
        <i class="bi ${escapeAttribute(icon)}" aria-hidden="true"></i>
        <strong></strong>
        <span></span>
      </div>
    `;
    const body = previewStage.querySelector(".file-manager-preview-unavailable");
    body.querySelector("strong").textContent = title || "Preview unavailable";
    body.querySelector("span").textContent = message || "This file cannot be previewed here.";
    if (actionUrl && actionLabel) {
      const action = document.createElement("a");
      action.className = "btn btn-accent btn-sm";
      action.href = actionUrl;
      action.textContent = actionLabel;
      body.appendChild(action);
    }
  }

  function directDownloadUrl(url) {
    const downloadUrl = new URL(url, window.location.origin);
    downloadUrl.searchParams.set("download", "1");
    return downloadUrl.toString();
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
