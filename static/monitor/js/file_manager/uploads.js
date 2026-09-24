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
