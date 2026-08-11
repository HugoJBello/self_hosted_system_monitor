(function () {
  let activeInput = null;
  let parentModalElement = null;

  function modalForId(id) {
    const element = document.getElementById(id);
    return element ? bootstrap.Modal.getOrCreateInstance(element) : null;
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = value || "";
    return node.innerHTML;
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setCurrentPath(modalElement, path) {
    if (!path) return;
    modalElement.dataset.currentPath = path;
    const currentPathNode = modalElement.querySelector("[data-path-browser-current-path]");
    if (currentPathNode) currentPathNode.textContent = path;
    modalElement.querySelectorAll(".backup-browser-node.is-current-path").forEach((node) => {
      node.classList.remove("is-current-path");
    });
    const currentNode = Array.from(modalElement.querySelectorAll(".backup-browser-node")).find((node) => node.dataset.path === path);
    if (currentNode) currentNode.classList.add("is-current-path");
  }

  function createNode(item) {
    const node = document.createElement("div");
    node.className = `backup-browser-node nested${item.is_mounted ? " is-mounted-path" : ""}`;
    node.dataset.path = item.path;
    node.innerHTML = `
      <button type="button" class="backup-browser-toggle" data-path="${escapeHtml(item.path)}" aria-label="Expand ${escapeHtml(item.name)}">
        <i class="bi bi-chevron-right"></i>
      </button>
      <button type="button" class="backup-browser-select" data-path="${escapeHtml(item.path)}">
        <i class="bi bi-folder2"></i>
        <span>${escapeHtml(item.name)}</span>
        ${item.is_mounted ? '<span class="path-browser-mounted-badge">Mounted</span>' : ""}
      </button>
      <div class="backup-browser-children"></div>
    `;
    return node;
  }

  function renderChildren(container, items) {
    container.innerHTML = "";
    if (!items.length) {
      container.innerHTML = `
        <div class="backup-browser-message">
          <i class="bi bi-folder-x"></i>
          <span>No readable subfolders found.</span>
        </div>
      `;
      return;
    }
    items.forEach((item) => {
      container.appendChild(createNode(item));
    });
  }

  async function loadChildren(path, targetNode, modalElement) {
    setCurrentPath(modalElement, path);
    const childrenContainer = targetNode.querySelector(".backup-browser-children");
    if (!childrenContainer) return;
    if (targetNode.dataset.loaded === "1") {
      childrenContainer.classList.toggle("open");
      targetNode.classList.toggle("is-open", childrenContainer.classList.contains("open"));
      return;
    }
    const treeUrl = modalElement.dataset.treeUrl;
    childrenContainer.innerHTML = `
      <div class="backup-browser-message">
        <span class="spinner-border spinner-border-sm" aria-hidden="true"></span>
        <span>Loading folders...</span>
      </div>
    `;
    childrenContainer.classList.add("open");
    targetNode.classList.add("is-open");
    try {
      const response = await fetch(`${treeUrl}?path=${encodeURIComponent(path)}`);
      const payload = await response.json();
      if (!response.ok || payload.error) {
        throw new Error(payload.error || "Could not load this folder.");
      }
      renderChildren(childrenContainer, payload.items || []);
      targetNode.dataset.loaded = "1";
    } catch (error) {
      childrenContainer.innerHTML = `
        <div class="backup-browser-message is-error">
          <i class="bi bi-exclamation-triangle"></i>
          <span>${escapeHtml(error.message || "Could not load this folder.")}</span>
        </div>
      `;
    }
  }

  async function refreshChildren(path, modalElement) {
    const targetNode = Array.from(modalElement.querySelectorAll(".backup-browser-node")).find((node) => node.dataset.path === path);
    if (!targetNode) return;
    targetNode.dataset.loaded = "0";
    const childrenContainer = targetNode.querySelector(".backup-browser-children");
    if (childrenContainer) childrenContainer.classList.add("open");
    targetNode.classList.add("is-open");
    await loadChildren(path, targetNode, modalElement);
  }

  async function createFolder(modalElement, form) {
    const input = form.querySelector("[data-path-browser-folder-name]");
    const messageNode = form.querySelector("[data-path-browser-create-message]");
    const folderName = (input ? input.value : "").trim();
    const parentPath = modalElement.dataset.currentPath || modalElement.querySelector(".backup-browser-node")?.dataset.path || "/";
    if (messageNode) {
      messageNode.className = "path-browser-create-message";
      messageNode.textContent = "";
    }
    if (!folderName) {
      if (messageNode) {
        messageNode.classList.add("is-error");
        messageNode.textContent = "Folder name is required.";
      }
      return;
    }
    const submitButton = form.querySelector("button[type='submit']");
    if (submitButton) submitButton.disabled = true;
    try {
      const body = new URLSearchParams();
      body.set("parent_path", parentPath);
      body.set("folder_name", folderName);
      const response = await fetch(modalElement.dataset.treeUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": csrfToken(),
        },
        body,
      });
      const payload = await response.json();
      if (!response.ok || payload.error) {
        throw new Error(payload.error || "Could not create folder.");
      }
      if (input) input.value = "";
      if (activeInput && payload.item && payload.item.path) {
        activeInput.value = payload.item.path;
        activeInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      await refreshChildren(parentPath, modalElement);
      if (payload.item && payload.item.path) {
        setCurrentPath(modalElement, payload.item.path);
      }
      if (messageNode) {
        messageNode.classList.add("is-success");
        messageNode.textContent = `Created ${payload.item.path}.`;
      }
    } catch (error) {
      if (messageNode) {
        messageNode.classList.add("is-error");
        messageNode.textContent = error.message || "Could not create folder.";
      }
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  }

  document.querySelectorAll("[data-path-browser-modal]").forEach((modalElement) => {
    modalElement.addEventListener("hidden.bs.modal", () => {
      if (parentModalElement) {
        window.setTimeout(() => {
          bootstrap.Modal.getOrCreateInstance(parentModalElement).show();
          parentModalElement = null;
        }, 0);
      }
    });
    modalElement.addEventListener("shown.bs.modal", () => {
      if (parentModalElement) {
        const parentInstance = bootstrap.Modal.getInstance(parentModalElement);
        if (parentInstance) parentInstance.hide();
      }
      const initialPath = activeInput && activeInput.value ? activeInput.value : modalElement.querySelector(".backup-browser-node")?.dataset.path;
      setCurrentPath(modalElement, initialPath);
    });
  });

  document.querySelectorAll("[data-path-browser-input]").forEach((input) => {
    input.addEventListener("focus", () => {
      activeInput = input;
    });
  });

  document.querySelectorAll("[data-path-browser-picker]").forEach((button) => {
    button.addEventListener("click", () => {
      activeInput = document.getElementById(button.dataset.inputId);
      parentModalElement = button.closest(".modal");
      const modal = modalForId(button.dataset.browserModalId);
      if (modal) modal.show();
    });
  });

  document.addEventListener("click", async (event) => {
    const toggle = event.target.closest(".backup-browser-toggle");
    const select = event.target.closest(".backup-browser-select");
    const modalElement = event.target.closest("[data-path-browser-modal]");
    if (!modalElement || (!toggle && !select)) return;

    if (toggle) {
      event.preventDefault();
      const node = toggle.closest(".backup-browser-node");
      await loadChildren(toggle.dataset.path, node, modalElement);
    }
    if (select) {
      event.preventDefault();
      setCurrentPath(modalElement, select.dataset.path);
      if (activeInput) {
        activeInput.value = select.dataset.path;
        activeInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      bootstrap.Modal.getOrCreateInstance(modalElement).hide();
    }
  });

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-path-browser-create-form]");
    if (!form) return;
    const modalElement = form.closest("[data-path-browser-modal]");
    if (!modalElement) return;
    event.preventDefault();
    await createFolder(modalElement, form);
  });
})();
