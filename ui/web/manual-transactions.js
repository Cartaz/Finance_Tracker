(() => {
  "use strict";

  let backend = null;
  let snapshot = null;

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
  const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const call = (method, ...args) => new Promise((resolve) => backend[method](...args, resolve));
  const unwrap = (result) => {
    if (!result?.ok) throw new Error(result?.error?.message || "Operazione fallita");
    return result.data;
  };

  function toast(message, bad = false) {
    const target = $("toast");
    if (!target) return;
    target.textContent = message;
    target.className = bad ? "show bad" : "show";
    window.setTimeout(() => { target.className = ""; }, 2800);
  }

  function option(account, label = account.name) {
    return `<option value="${account.id}">${escapeHtml(label)}${account.currency ? ` · ${escapeHtml(account.currency)}` : ""}</option>`;
  }

  function balanceAccounts() {
    return (snapshot?.accounts || []).filter((item) => ["ASSET", "LIABILITY"].includes(item.type) && !item.placeholder && !item.archived);
  }

  function accountById(id) {
    return (snapshot?.accounts || []).find((item) => String(item.id) === String(id));
  }

  function categoryPath(category) {
    const byId = new Map((snapshot?.accounts || []).map((item) => [String(item.id), item]));
    const names = [];
    const seen = new Set();
    let current = category;
    while (current) {
      const id = String(current.id);
      if (seen.has(id)) break;
      seen.add(id);
      names.push(current.name);
      current = current.parentId == null ? null : byId.get(String(current.parentId));
    }
    return names.reverse().join(" › ");
  }

  function eligibleCounters(sourceId, kind) {
    const source = accountById(sourceId);
    if (!source) return [];
    const allowed = new Set((source.postingCapabilities?.[kind] || []).map(String));
    return (snapshot?.accounts || []).filter((item) => allowed.has(String(item.id)));
  }

  function refreshIncomeCategories() {
    const accountId = $("income-account")?.value;
    const select = $("income-category");
    if (!select) return;
    const categories = eligibleCounters(accountId, "INCOME");
    select.innerHTML = categories.map((item) => option(item, categoryPath(item))).join("");
    $("income-submit").disabled = categories.length === 0;
  }

  function refreshTransferDestinations() {
    const sourceId = $("transfer-source")?.value;
    const select = $("transfer-destination");
    if (!select) return;
    const destinations = eligibleCounters(sourceId, "TRANSFER");
    select.innerHTML = destinations.map((item) => option(item)).join("");
    $("transfer-submit").disabled = destinations.length === 0;
  }

  function renderOptions() {
    const accounts = balanceAccounts();
    const accountOptions = accounts.map((item) => option(item)).join("");
    $("income-account").innerHTML = accountOptions;
    $("transfer-source").innerHTML = accountOptions;
    refreshIncomeCategories();
    refreshTransferDestinations();
  }

  async function refreshSnapshot() {
    if (!backend || $("app")?.classList.contains("hidden")) return;
    snapshot = unwrap(await call("getSnapshot"));
    renderOptions();
  }

  function installForms() {
    const expenseForm = $("expense-form");
    const split = $("transactions")?.querySelector(":scope > .split");
    if (!expenseForm || !split || $("manual-transaction-forms")) return;

    const stack = document.createElement("div");
    stack.id = "manual-transaction-forms";
    stack.className = "stack";
    split.replaceChild(stack, expenseForm);
    stack.appendChild(expenseForm);

    const incomeForm = document.createElement("form");
    incomeForm.id = "income-form";
    incomeForm.className = "card form-card";
    incomeForm.innerHTML = `
      <h3>Nuova entrata</h3>
      <label>Conto di accredito<select name="destinationAccountId" id="income-account" required></select></label>
      <label>Categoria di entrata<select name="incomeAccountId" id="income-category" required></select></label>
      <label>Importo<input name="amount" required inputmode="decimal" placeholder="1800,00"></label>
      <label>Data<input name="date" type="date" required></label>
      <label>Ora opzionale<input name="time" type="time"></label>
      <label>Descrizione<input name="description" placeholder="Stipendio agosto"></label>
      <button id="income-submit" type="submit">Registra entrata</button>`;
    stack.appendChild(incomeForm);

    const transferForm = document.createElement("form");
    transferForm.id = "transfer-form";
    transferForm.className = "card form-card";
    transferForm.innerHTML = `
      <h3>Nuovo giroconto</h3>
      <p class="empty form-note">Sposta denaro tra due conti della stessa valuta senza creare un'entrata o una spesa.</p>
      <label>Da<select name="sourceAccountId" id="transfer-source" required></select></label>
      <label>A<select name="destinationAccountId" id="transfer-destination" required></select></label>
      <label>Importo<input name="amount" required inputmode="decimal" placeholder="100,00"></label>
      <label>Data<input name="date" type="date" required></label>
      <label>Ora opzionale<input name="time" type="time"></label>
      <label>Descrizione<input name="description" placeholder="Da conto corrente a contanti"></label>
      <button id="transfer-submit" type="submit">Registra giroconto</button>`;
    stack.appendChild(transferForm);

    incomeForm.elements.date.value = localDate();
    transferForm.elements.date.value = localDate();
    $("income-account").addEventListener("change", refreshIncomeCategories);
    $("transfer-source").addEventListener("change", refreshTransferDestinations);

    incomeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(incomeForm));
        unwrap(await call("createIncome", data));
        const date = incomeForm.elements.date.value;
        incomeForm.reset();
        incomeForm.elements.date.value = date;
        await refreshSnapshot();
        $("refresh")?.click();
        toast("Entrata registrata");
      } catch (error) {
        toast(error.message, true);
      }
    });

    transferForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(transferForm));
        unwrap(await call("createTransfer", data));
        const date = transferForm.elements.date.value;
        transferForm.reset();
        transferForm.elements.date.value = date;
        await refreshSnapshot();
        $("refresh")?.click();
        toast("Giroconto registrato");
      } catch (error) {
        toast(error.message, true);
      }
    });

    document.querySelector('[data-view="transactions"]')?.addEventListener("click", () => {
      refreshSnapshot().catch((error) => toast(error.message, true));
    });
    $("refresh")?.addEventListener("click", () => {
      window.setTimeout(() => refreshSnapshot().catch((error) => toast(error.message, true)), 0);
    });
  }

  function start() {
    backend = window.financeTrackerBackend;
    if (!backend) return;
    installForms();
    refreshSnapshot().catch(() => {});
  }

  window.addEventListener("finance-backend-ready", start, { once: true });
  if (window.financeTrackerBackend) start();
})();
