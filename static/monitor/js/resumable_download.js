(function () {
  const DEFAULT_THRESHOLD = 100 * 1024 * 1024;
  const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024;
  let transfer = null;

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function ensurePanel() {
    let panel = document.querySelector("[data-resumable-download-panel]");
    if (panel) return panel;
    panel = document.createElement("section");
    panel.className = "resumable-download-panel d-none";
    panel.dataset.resumableDownloadPanel = "";
    panel.setAttribute("aria-live", "polite");
    panel.innerHTML = `
      <div class="resumable-download-heading">
        <span class="resumable-download-icon"><i class="bi bi-cloud-arrow-down"></i></span>
        <div><strong data-resumable-name>Large download</strong><small data-resumable-status>Waiting</small></div>
        <button type="button" class="btn-close btn-close-white" data-resumable-dismiss aria-label="Hide download panel"></button>
      </div>
      <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"><div class="progress-bar" data-resumable-progress style="width:0%">0%</div></div>
      <div class="resumable-download-meta"><span data-resumable-bytes>0 B</span><span data-resumable-speed></span></div>
      <div class="resumable-download-actions">
        <button type="button" class="btn btn-outline-light btn-sm" data-resumable-pause><i class="bi bi-pause-fill"></i> Pause</button>
        <button type="button" class="btn btn-outline-light btn-sm d-none" data-resumable-retry><i class="bi bi-arrow-clockwise"></i> Retry</button>
        <a class="btn btn-outline-light btn-sm d-none" data-resumable-native><i class="bi bi-browser-chrome"></i> Browser download</a>
        <button type="button" class="btn btn-outline-danger btn-sm" data-resumable-stop><i class="bi bi-x-circle"></i> Stop</button>
      </div>`;
    document.body.appendChild(panel);
    panel.querySelector("[data-resumable-pause]").addEventListener("click", togglePause);
    panel.querySelector("[data-resumable-retry]").addEventListener("click", resumeTransfer);
    panel.querySelector("[data-resumable-stop]").addEventListener("click", stopTransfer);
    panel.querySelector("[data-resumable-dismiss]").addEventListener("click", () => panel.classList.add("d-none"));
    return panel;
  }

  function updatePanel(message, state = "running") {
    if (!transfer) return;
    const panel = ensurePanel();
    panel.classList.remove("d-none", "is-error", "is-complete");
    panel.classList.toggle("is-error", state === "error");
    panel.classList.toggle("is-complete", state === "complete");
    panel.querySelector("[data-resumable-name]").textContent = transfer.name;
    panel.querySelector("[data-resumable-status]").textContent = message;
    const percent = transfer.size ? Math.min(100, Math.round((transfer.offset / transfer.size) * 100)) : 0;
    const progress = panel.querySelector("[data-resumable-progress]");
    progress.style.width = `${percent}%`;
    progress.textContent = `${percent}%`;
    panel.querySelector("[data-resumable-bytes]").textContent = `${formatBytes(transfer.offset)} of ${formatBytes(transfer.size)}`;
    const elapsed = Math.max((performance.now() - transfer.startedAt) / 1000, .1);
    panel.querySelector("[data-resumable-speed]").textContent = transfer.offset && state === "running" ? `${formatBytes(transfer.offset / elapsed)}/s` : "";
    panel.querySelector("[data-resumable-pause]").classList.toggle("d-none", ["error", "complete", "stopped"].includes(state));
    panel.querySelector("[data-resumable-retry]").classList.toggle("d-none", state !== "error");
    const nativeDownload = panel.querySelector("[data-resumable-native]");
    nativeDownload.classList.toggle("d-none", state !== "error");
    nativeDownload.href = transfer.url;
    panel.querySelector("[data-resumable-stop]").classList.toggle("d-none", state === "complete");
  }

  async function beginManagedDownload(anchor) {
    const size = Number(anchor.dataset.downloadSize) || 0;
    const threshold = Number(anchor.dataset.downloadThreshold) || DEFAULT_THRESHOLD;
    const supportsPicker = typeof window.showSaveFilePicker === "function";
    const supportsOriginStorage = Boolean(navigator.storage?.getDirectory);
    if (size < threshold || (!supportsPicker && !supportsOriginStorage)) return false;
    if (transfer && !["complete", "stopped"].includes(transfer.state)) {
      ensurePanel().classList.remove("d-none");
      return true;
    }
    let fileHandle;
    let storageRoot = null;
    let storageName = "";
    try {
      if (supportsPicker) {
        fileHandle = await window.showSaveFilePicker({suggestedName: anchor.dataset.downloadName || "download"});
      } else {
        storageRoot = await navigator.storage.getDirectory();
        storageName = `system-monitor-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}.part`;
        fileHandle = await storageRoot.getFileHandle(storageName, {create: true});
      }
    } catch (error) {
      if (error.name !== "AbortError") window.location.assign(anchor.href);
      return true;
    }
    const writable = await fileHandle.createWritable();
    transfer = {
      url: anchor.href,
      name: anchor.dataset.downloadName || fileHandle.name || "download",
      size,
      chunkSize: Number(anchor.dataset.downloadChunkSize) || DEFAULT_CHUNK_SIZE,
      offset: 0,
      etag: "",
      writable,
      fileHandle,
      storageRoot,
      storageName,
      controller: null,
      state: "running",
      startedAt: performance.now(),
    };
    updatePanel(`Downloading in ${formatBytes(transfer.chunkSize)} resumable chunks.`);
    downloadNextChunks();
    return true;
  }

  async function downloadNextChunks() {
    if (!transfer || transfer.state !== "running") return;
    try {
      while (transfer.offset < transfer.size && transfer.state === "running") {
        const end = Math.min(transfer.offset + transfer.chunkSize, transfer.size) - 1;
        transfer.controller = new AbortController();
        const headers = {Range: `bytes=${transfer.offset}-${end}`};
        if (transfer.etag) headers["If-Range"] = transfer.etag;
        const response = await fetch(transfer.url, {headers, credentials: "same-origin", signal: transfer.controller.signal});
        if (response.status !== 206) throw new Error(`Server did not honor byte range (${response.status}).`);
        const contentRange = response.headers.get("Content-Range") || "";
        if (!contentRange.startsWith(`bytes ${transfer.offset}-`)) throw new Error("Server returned an unexpected byte range.");
        const nextEtag = response.headers.get("ETag") || "";
        if (transfer.etag && nextEtag && nextEtag !== transfer.etag) throw new Error("The source file changed during download.");
        transfer.etag = transfer.etag || nextEtag;
        const chunk = await response.arrayBuffer();
        if (!chunk.byteLength) throw new Error("Server returned an empty download chunk.");
        await transfer.writable.write({type: "write", position: transfer.offset, data: chunk});
        transfer.offset += chunk.byteLength;
        updatePanel("Downloading with recovery enabled.");
      }
      if (transfer.state === "running" && transfer.offset >= transfer.size) {
        await transfer.writable.close();
        if (transfer.storageRoot) {
          const completedFile = await transfer.fileHandle.getFile();
          const objectUrl = URL.createObjectURL(completedFile);
          const saveLink = document.createElement("a");
          saveLink.href = objectUrl;
          saveLink.download = transfer.name;
          saveLink.className = "d-none";
          document.body.appendChild(saveLink);
          saveLink.click();
          const completedStorageRoot = transfer.storageRoot;
          const completedStorageName = transfer.storageName;
          window.setTimeout(async () => {
            URL.revokeObjectURL(objectUrl);
            saveLink.remove();
            try { await completedStorageRoot.removeEntry(completedStorageName); } catch (_) {}
          }, 120000);
        }
        transfer.state = "complete";
        updatePanel("Download complete. Open the folder you selected (usually Downloads) to open the file.", "complete");
      }
    } catch (error) {
      if (!transfer || transfer.state === "paused" || transfer.state === "stopped") return;
      transfer.state = "error";
      updatePanel(`${error.message || "Download interrupted."} Retry continues from the last completed chunk.`, "error");
    }
  }

  function togglePause() {
    if (!transfer) return;
    if (transfer.state === "paused") {
      resumeTransfer();
      return;
    }
    transfer.state = "paused";
    transfer.controller?.abort();
    const button = ensurePanel().querySelector("[data-resumable-pause]");
    button.innerHTML = '<i class="bi bi-play-fill"></i> Resume';
    updatePanel("Paused. The completed chunks are kept in this session.", "paused");
  }

  function resumeTransfer() {
    if (!transfer || !["paused", "error"].includes(transfer.state)) return;
    transfer.state = "running";
    const panel = ensurePanel();
    panel.querySelector("[data-resumable-pause]").innerHTML = '<i class="bi bi-pause-fill"></i> Pause';
    panel.querySelector("[data-resumable-retry]").classList.add("d-none");
    updatePanel("Resuming from the last completed chunk.");
    downloadNextChunks();
  }

  async function stopTransfer() {
    if (!transfer || transfer.state === "complete") return;
    transfer.state = "stopped";
    transfer.controller?.abort();
    try { await transfer.writable.abort(); } catch (_) {}
    if (transfer.storageRoot) {
      try { await transfer.storageRoot.removeEntry(transfer.storageName); } catch (_) {}
    }
    updatePanel("Download stopped. The incomplete output was discarded.", "stopped");
  }

  function decorateLargeDownloads() {
    document.querySelectorAll("[data-managed-download]").forEach((anchor) => {
      const size = Number(anchor.dataset.downloadSize) || 0;
      const threshold = Number(anchor.dataset.downloadThreshold) || DEFAULT_THRESHOLD;
      if (size < threshold || anchor.querySelector(".resumable-download-badge")) return;
      const badge = document.createElement("small");
      badge.className = "resumable-download-badge";
      badge.innerHTML = '<i class="bi bi-arrow-repeat"></i> Resumable';
      anchor.appendChild(badge);
      anchor.title = "Large download: transferred in chunks with recovery support";
    });
  }

  document.addEventListener("click", async (event) => {
    const anchor = event.target.closest("a[data-managed-download]");
    if (!anchor || anchor.classList.contains("disabled")) return;
    const size = Number(anchor.dataset.downloadSize) || 0;
    const threshold = Number(anchor.dataset.downloadThreshold) || DEFAULT_THRESHOLD;
    if (size < threshold) return;
    if (typeof window.showSaveFilePicker !== "function" && !navigator.storage?.getDirectory) {
      anchor.title = "Your browser download manager can resume this download if it is interrupted.";
      return;
    }
    event.preventDefault();
    await beginManagedDownload(anchor);
  });

  window.ResumableDownloads = {decorate: decorateLargeDownloads, formatBytes};
  document.addEventListener("DOMContentLoaded", decorateLargeDownloads);
})();
