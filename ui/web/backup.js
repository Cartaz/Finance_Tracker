(() => {
  "use strict";

  let backend = null;
  const $ = (id) => document.getElementById(id);
  const call = (method, ...args) => new Promise((resolve) => backend[method](...args, resolve));
  const unwrap = (result) => {
    if (!result?.ok) throw new Error(result?.error?.message || "Operazione fallita");
    return result.data;
  };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[char]));

  function showToast(message, bad = false) {
    const toast = $("toast");
    toast.textContent = message;
    toast.className = bad ? "show bad" : "show";
    setTimeout(() => { toast.className = ""; }, 3200);
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  }

  function formatUtc(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "") : date.toLocaleString("it-IT");
  }

  function setMaintenance(active) {
    document.body.classList.toggle("maintenance", Boolean(active));
    $("maintenance-banner").classList.toggle("hidden", !active);
  }

  async function refreshBackups() {
    if (!backend) return;
    const items = unwrap(await call("listBackups"));
    $("backup-list").innerHTML = items.map((item) => `
      <div class="backup-row">
        <div><b>${escapeHtml(item.name)}</b><br><small>${formatUtc(item.modifiedUtc)} · ${formatBytes(item.sizeBytes)} · schema v${item.schemaVersion}</small></div>
        <button type="button" data-backup-restore="${escapeHtml(item.name)}">Ripristina</button>
      </div>
    `).join("") || `<p class="empty">Nessun backup locale.</p>`;
  }

  async function start(method, ...args) {
    const result = unwrap(await call(method, ...args));
    if (result?.cancelled) return null;
    return result;
  }

  $("backup-create").addEventListener("click", async () => {
    try {
      const task = await start("startManagedBackup");
      if (task) showToast("Creazione backup avviata");
    } catch (error) { showToast(error.message, true); }
  });

  $("backup-export").addEventListener("click", async () => {
    try {
      const task = await start("startExportBackup");
      if (task) showToast("Esportazione backup avviata");
    } catch (error) { showToast(error.message, true); }
  });

  $("backup-restore-file").addEventListener("click", async () => {
    if (!window.confirm("Ripristinare un backup sostituirà lo stato corrente. Verrà creato automaticamente un backup di sicurezza. Continuare?")) return;
    try {
      const task = await start("startExternalRestore");
      if (task) showToast("Verifica del backup avviata");
    } catch (error) { showToast(error.message, true); }
  });

  $("backup-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-backup-restore]");
    if (!button) return;
    const name = button.dataset.backupRestore;
    if (!window.confirm(`Ripristinare ${name}? Lo stato corrente verrà salvato automaticamente prima del restore.`)) return;
    try {
      await start("startManagedRestore", name);
      showToast("Verifica del backup avviata");
    } catch (error) { showToast(error.message, true); }
  });

  if (typeof QWebChannel === "undefined" || !window.qt?.webChannelTransport) return;
  new QWebChannel(window.qt.webChannelTransport, async (channel) => {
    backend = channel.objects.backend;
    backend.maintenanceChanged.connect((active) => setMaintenance(active));
    backend.backupTaskFinished.connect(async (result) => {
      if (!result?.ok) {
        showToast(result?.error?.message || "Operazione backup fallita", true);
        return;
      }
      if (result.requiresReload) {
        const safety = result.data?.safetyBackup ? ` Backup di sicurezza: ${result.data.safetyBackup}.` : "";
        showToast(`Ripristino completato.${safety}`);
        window.location.reload();
        return;
      }
      if (result.operation === "BACKUP_CREATE") showToast("Backup locale creato");
      else if (result.operation === "BACKUP_EXPORT") showToast("Backup esportato");
      try { await refreshBackups(); } catch (error) { showToast(error.message, true); }
    });
    try { await refreshBackups(); } catch (error) { showToast(error.message, true); }
  });
})();
