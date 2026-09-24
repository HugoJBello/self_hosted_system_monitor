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
        const downloadSize = Number(payload.download_size_bytes) || 0;
        const managedThreshold = Number(payload.managed_download_threshold) || (100 * 1024 * 1024);
        const useManagedDownload = downloadSize >= managedThreshold;
        setDownloadStatus(useManagedDownload
          ? "Large archive ready. Use Download ZIP for chunked transfer with pause and recovery."
          : "Browser download started. When it finishes, open your Downloads folder to open the ZIP.");
        if (downloadReady) {
          downloadReady.href = payload.download_url;
          downloadReady.classList.remove("disabled");
          downloadReady.dataset.downloadSize = String(downloadSize);
          downloadReady.dataset.downloadThreshold = String(managedThreshold);
          downloadReady.dataset.downloadChunkSize = String(payload.download_chunk_size || "");
          downloadReady.dataset.downloadName = `file-manager-download-${payload.id}.zip`;
          window.ResumableDownloads?.decorate();
        }
        if (!useManagedDownload) triggerBrowserDownload(payload.download_url);
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
