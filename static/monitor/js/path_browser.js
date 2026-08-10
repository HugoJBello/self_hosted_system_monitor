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
      const node = document.createElement("div");
      node.className = "backup-browser-node nested";
      node.dataset.path = item.path;
      node.innerHTML = `
        <button type="button" class="backup-browser-toggle" data-path="${escapeHtml(item.path)}" aria-label="Expand ${escapeHtml(item.name)}">
          <i class="bi bi-chevron-right"></i>
        </button>
        <button type="button" class="backup-browser-select" data-path="${escapeHtml(item.path)}">
          <i class="bi bi-folder2"></i>
          <span>${escapeHtml(item.name)}</span>
        </button>
        <div class="backup-browser-children"></div>
      `;
      container.appendChild(node);
    });
  }

  async function loadChildren(path, targetNode, modalElement) {
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
      if (activeInput) {
        activeInput.value = select.dataset.path;
        activeInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      bootstrap.Modal.getOrCreateInstance(modalElement).hide();
    }
  });
})();
