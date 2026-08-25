(() => {
  "use strict";
  let backend = null;
  let state = null;
  let currentBatchId = null;
  let currentImportRows = new Map();
  let currencySpecs = new Map();
  let supportedCurrencies = [];
  const $ = (id) => document.getElementById(id);
  const call = (method, ...args) => new Promise((resolve) => backend[method](...args, resolve));
  const toast = (message, bad = false) => { $("toast").textContent = message; $("toast").className = bad ? "show bad" : "show"; setTimeout(() => $("toast").className = "", 2800); };
  const unwrap = (result) => { if (!result?.ok) throw new Error(result?.error?.message || "Operazione fallita"); return result.data; };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const localMonth = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  const currencyDigits = (currency) => {
    const digits = currencySpecs.get(currency);
    if (digits == null) throw new Error(`Valuta non supportata: ${currency}`);
    return digits;
  };
  const money = (minor, currency) => {
    if (minor == null) return "FX mancante";
    const digits = currencyDigits(currency);
    const value = BigInt(String(minor));
    const negative = value < 0n;
    const absolute = negative ? -value : value;
    const scale = 10n ** BigInt(digits);
    const whole = absolute / scale;
    const fraction = absolute % scale;
    const wholeText = new Intl.NumberFormat("it-IT").format(whole);
    const fractionText = digits ? `,${fraction.toString().padStart(digits, "0")}` : "";
    return `${negative ? "−" : ""}${wholeText}${fractionText} ${currency}`;
  };
  const percentBps = (bps) => {
    if (bps == null) return "—";
    const value = BigInt(String(bps));
    const negative = value < 0n;
    const absolute = negative ? -value : value;
    return `${negative ? "−" : ""}${absolute / 100n},${(absolute % 100n).toString().padStart(2, "0")}%`;
  };

  function currencyOptions(items, selected = null) {
    return items.map((item) => `<option value="${item.code}"${item.code === selected ? " selected" : ""}>${item.code}</option>`).join("");
  }

  function configureCurrencies(items, baseCurrency = null, preferredCurrency = null) {
    supportedCurrencies = items;
    currencySpecs = new Map(items.map((item) => [item.code, item.minorUnitDigits]));
    const setupCurrency = preferredCurrency && currencySpecs.has(preferredCurrency) ? preferredCurrency : items[0]?.code;
    $("setup-form").elements.currency.innerHTML = currencyOptions(items, setupCurrency);
    $("account-form").elements.currency.innerHTML = currencyOptions(items, baseCurrency || setupCurrency);
    const fxItems = baseCurrency ? items.filter((item) => item.code !== baseCurrency) : items;
    $("fx-form").elements.currency.innerHTML = currencyOptions(fxItems);
  }

  function reportPeriod() {
    return { startDate: $("report-start").value, endDate: $("report-end").value, asOfDate: $("report-asof").value };
  }

  function forecastPeriod() {
    return { startDate: $("forecast-start").value, endDate: $("forecast-end").value, granularity: $("forecast-granularity").value };
  }

  function initializeDates() {
    const now = new Date();
    $("report-asof").value = localDate(now);
    $("report-end").value = localDate(now);
    $("report-start").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
    $("fx-form").elements.date.value = localDate(now);
    $("scheduled-form").elements.startDate.value = localDate(now);
    $("scheduled-asof").value = localDate(now);
    $("budget-period").value = localMonth(now);
    $("forecast-start").value = localDate(now);
    const forecastEnd = new Date(now);
    forecastEnd.setMonth(forecastEnd.getMonth() + 6);
    $("forecast-end").value = localDate(forecastEnd);
  }

  function optionsForAccountIds(accountIds) {
    const allowed = new Set((accountIds || []).map(String));
    return (state?.accounts || []).filter((item) => allowed.has(String(item.id))).map((a) => `<option value="${a.id}">${escapeHtml(a.name)}${a.currency ? ` · ${a.currency}` : ""}</option>`).join("");
  }

  function scheduledCounterOptions(kind, sourceId) {
    const source = state?.accounts.find((item) => String(item.id) === String(sourceId));
    if (!source) return "";
    return optionsForAccountIds(source.postingCapabilities?.[kind] || []);
  }

  function refreshScheduledCounter() {
    if (!state) return;
    $("scheduled-counter").innerHTML = scheduledCounterOptions($("scheduled-kind").value, $("scheduled-source").value);
  }

  function renderSnapshot(snapshot) {
    state = snapshot;
    $("book-name").textContent = snapshot.book.name.toUpperCase();
    const balanceAccounts = snapshot.accounts.filter((a) => ["ASSET", "LIABILITY"].includes(a.type));
    const txRows = snapshot.transactions.map((t) => `<div class="row"><span>${t.transaction_date}</span><b>${escapeHtml(t.payee_name || t.description || t.kind)}</b><small>${t.kind}</small></div>`).join("") || `<p class="empty">Nessuna transazione.</p>`;
    $("recent").innerHTML = txRows;
    $("transactions-list").innerHTML = txRows;
    $("accounts-list").innerHTML = snapshot.accounts.map((a) => `<div class="row"><b>${escapeHtml(a.name)}</b><small>${a.type}${a.currency ? ` · ${a.currency}` : ""}</small><span>${a.balanceMinor == null ? "" : money(a.balanceMinor, a.currency)}</span></div>`).join("") || `<p class="empty">Crea il primo conto.</p>`;
    $("expense-account").innerHTML = balanceAccounts.filter((a) => !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.currency}</option>`).join("");
    $("expense-category").innerHTML = snapshot.accounts.filter((a) => a.type === "EXPENSE" && !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
    $("history-account").innerHTML = balanceAccounts.map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.currency}</option>`).join("");
    $("import-account").innerHTML = balanceAccounts.filter((a) => !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.currency}</option>`).join("");
    $("scheduled-source").innerHTML = balanceAccounts.filter((a) => !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.currency}</option>`).join("");
    refreshScheduledCounter();
  }

  function renderDashboard(report) {
    const o = report.overview;
    const currency = report.baseCurrency;
    $("metrics").innerHTML = [
      ["Patrimonio netto", money(o.netWorthMinor, currency)],
      ["Entrate", money(o.incomeMinor, currency)],
      ["Uscite", money(o.expenseMinor, currency)],
      ["Saving rate", percentBps(o.savingRateBps)],
    ].map(([label, value]) => `<article class="card metric"><span>${label}</span><strong>${value}</strong></article>`).join("");
    const missing = o.missingFx || [];
    $("fx-warning").classList.toggle("hidden", missing.length === 0);
    $("fx-warning").innerHTML = missing.length ? `<b>Reporting incompleto: tassi FX mancanti</b><div>${missing.map((item) => `${escapeHtml(item.currency)} · ${item.date}`).join(" · ")}</div>` : "";
    $("cash-flow").innerHTML = report.cashFlow.map((item) => `<div class="report-row"><b>${item.period}</b><span>Entrate ${money(item.incomeMinor, currency)}</span><span>Uscite ${money(item.expenseMinor, currency)}</span><strong>${money(item.netMinor, currency)}</strong></div>`).join("") || `<p class="empty">Nessun flusso nel periodo.</p>`;
    $("category-report").innerHTML = report.categories.map((item) => `<div class="report-row"><b>${escapeHtml(item.path)}</b><span>${item.transactionCount} movimenti</span><strong>${money(item.amountMinor, currency)}</strong></div>`).join("") || `<p class="empty">Nessuna spesa nel periodo.</p>`;
    $("merchant-report").innerHTML = report.merchants.map((item) => `<div class="report-row"><b>${escapeHtml(item.name)}</b><span>${item.transactionCount} movimenti</span><strong>${money(item.amountMinor, currency)}</strong></div>`).join("") || `<p class="empty">Nessun merchant nel periodo.</p>`;
  }

  function renderBudgets(report) {
    const currency = report.baseCurrency;
    const previousTarget = $("budget-category").value;
    $("budget-category").innerHTML = (report.targets || []).map((item) => `<option value="${item.categoryAccountId}">${escapeHtml(item.categoryPath)}${item.placeholder ? " · gruppo" : ""}${item.hasBudget ? " · budget esistente" : ""}</option>`).join("");
    if ([...$("budget-category").options].some((option) => option.value === previousTarget)) $("budget-category").value = previousTarget;
    $("budget-form").querySelector('button[type="submit"]').disabled = (report.targets || []).length === 0;
    $("budget-summary").innerHTML = `<div class="report-row"><b>${report.period}</b><span>Budget ${money(report.totalBudgetMinor, currency)}</span><span>Speso ${money(report.totalSpentMinor, currency)}</span><strong>Residuo ${money(report.totalRemainingMinor, currency)}</strong></div>`;
    const missing = report.missingFx || [];
    $("budget-warning").classList.toggle("hidden", missing.length === 0);
    $("budget-warning").innerHTML = missing.length ? `<b>Budget incompleto: tassi FX mancanti</b><div>${missing.map((item) => `${escapeHtml(item.currency)} · ${item.date}`).join(" · ")}</div>` : "";
    $("budget-list").innerHTML = report.budgets.map((item) => `<div class="card"><div class="report-row"><b>${escapeHtml(item.categoryPath)}</b><span>Utilizzo ${percentBps(item.usageBps)}</span><span>${money(item.spentMinor, currency)} / ${money(item.amountMinor, currency)}</span><strong>${item.remainingMinor == null ? "FX mancante" : `${item.overBudget ? "Oltre di " : "Residuo "}${money(item.overBudget ? -BigInt(String(item.remainingMinor)) : item.remainingMinor, currency)}`}</strong></div><div class="history-controls"><button type="button" data-budget-delete="${item.id}">Elimina</button></div></div>`).join("") || `<p class="empty">Nessun budget per questo mese.</p>`;
  }

  function renderForecast(report) {
    const currency = report.baseCurrency;
    $("forecast-metrics").innerHTML = [
      ["Entrate previste", money(report.totalInflowMinor, currency)],
      ["Uscite previste", money(report.totalOutflowMinor, currency)],
      ["Netto previsto", money(report.totalNetMinor, currency)],
      ["Occorrenze", `${report.occurrenceCount} · ${report.transferCount} trasferimenti`],
    ].map(([label, value]) => `<article class="card metric"><span>${label}</span><strong>${value}</strong></article>`).join("");
    const missing = report.missingFx || [];
    $("forecast-warning").classList.toggle("hidden", missing.length === 0);
    $("forecast-warning").innerHTML = missing.length ? `<b>Forecast incompleto: tassi FX mancanti</b><div>${missing.map((item) => `${escapeHtml(item.currency)} · ${item.date}`).join(" · ")}</div>` : "";
    $("forecast-buckets").innerHTML = report.buckets.map((item) => `<div class="report-row"><b>${item.period}</b><span>Entrate ${money(item.inflowMinor, currency)}</span><span>Uscite ${money(item.outflowMinor, currency)}</span><strong>${money(item.netMinor, currency)}</strong><small>${item.occurrenceCount} occorrenze · ${item.transferCount} transfer</small></div>`).join("") || `<p class="empty">Nessun flusso programmato nel periodo.</p>`;
    $("forecast-occurrences").innerHTML = report.occurrences.map((item) => `<div class="report-row"><span>${item.dueDate}</span><b>${escapeHtml(item.description || item.kind)}</b><span>${item.direction}</span><strong>${item.direction === "TRANSFER" ? money(item.amountMinor, item.currency) : money(item.baseAmountMinor, currency)}</strong><small>${item.kind}${item.currency !== currency ? ` · origine ${money(item.amountMinor, item.currency)}` : ""}</small></div>`).join("") || `<p class="empty">Nessuna occorrenza prevista.</p>`;
  }

  async function refreshReports() { renderDashboard(unwrap(await call("getDashboard", reportPeriod()))); }
  async function refreshBudgets() { renderBudgets(unwrap(await call("getBudgetStatus", { period: $("budget-period").value }))); }
  async function refreshForecast() { renderForecast(unwrap(await call("getForecast", forecastPeriod()))); }
  async function refreshFxRates() {
    const items = unwrap(await call("listFxRates"));
    $("fx-rates").innerHTML = items.map((item) => `<div class="mini-row"><span>${item.date}</span><b>${escapeHtml(item.currency)}</b><span>${escapeHtml(item.rate)}</span></div>`).join("") || `<p class="empty">Nessun tasso salvato.</p>`;
  }
  async function refreshScheduled() {
    const items = unwrap(await call("listScheduledTransactions"));
    $("scheduled-list").innerHTML = items.map((item) => `<div class="card"><div class="report-row"><b>${escapeHtml(item.description || item.kind)}</b><span>${escapeHtml(item.sourceAccountName)} → ${escapeHtml(item.counterAccountName)}</span><strong>${money(item.amountMinor, item.currency)}</strong><small>${item.frequency} × ${item.interval} · prossima ${item.nextDueDate}${item.endDate ? ` · fine ${item.endDate}` : ""} · ${item.active ? "ATTIVA" : "PAUSA"}</small></div><div class="history-controls"><button type="button" data-schedule-toggle="${item.id}" data-active="${item.active ? "0" : "1"}">${item.active ? "Pausa" : "Riattiva"}</button><button type="button" data-schedule-post="${item.id}">Registra dovute</button></div></div>`).join("") || `<p class="empty">Nessuna transazione programmata.</p>`;
  }
  async function refreshImportBatches() {
    const items = unwrap(await call("listImportBatches"));
    $("import-batches").innerHTML = items.map((item) => `<button type="button" class="row import-batch" data-batch-id="${item.id}"><b>${escapeHtml(item.source_name)}</b><span>${escapeHtml(item.account_name)}</span><small>${item.review_mode} · ${item.row_count} righe</small></button>`).join("") || `<p class="empty">Nessun import.</p>`;
  }
  function counterOptionsForRow(row, postingKind) {
    return optionsForAccountIds(row.postingCapabilities?.[postingKind] || []);
  }
  function candidateButton(rowId, candidate) {
    const detail = candidate.payee_name || candidate.description || candidate.kind || "Transazione";
    const currency = candidate.currency_code ? ` · ${candidate.currency_code}` : "";
    return `<button type="button" data-action="link" data-row-id="${rowId}" data-transaction-id="${candidate.id}">Collega #${candidate.id} · ${escapeHtml(detail)}${currency}</button>`;
  }
  function postingControls(row) {
    const kinds = Object.keys(row.postingCapabilities || {});
    if (!kinds.length) return "";
    const selectedKind = kinds[0];
    const kindOptions = kinds.map((kind) => `<option value="${kind}">${kind}</option>`).join("");
    return `<select data-posting-kind-row="${row.id}">${kindOptions}</select><select data-counter-row="${row.id}">${counterOptionsForRow(row, selectedKind)}</select><button type="button" data-action="post" data-row-id="${row.id}">Registra nel ledger</button>`;
  }
  async function loadImportBatch(batchId) {
    currentBatchId = String(batchId);
    const rows = unwrap(await call("getImportBatchRows", { batchId }));
    currentImportRows = new Map(rows.map((row) => [String(row.id), row]));
    $("import-rows").innerHTML = rows.map((row) => {
      const resolved = ["MATCHED", "POSTED", "IGNORED"].includes(row.review_state);
      const blocked = ["OUTSIDE_TRACKING", "TRACKING_AMBIGUOUS", "AMBIGUOUS"].includes(row.review_state);
      const candidates = (row.candidates || []).map((candidate) => candidateButton(row.id, candidate)).join("");
      const post = resolved || blocked ? "" : postingControls(row);
      const ignore = resolved ? "" : `<button type="button" data-action="ignore" data-row-id="${row.id}">Ignora</button>`;
      return `<div class="card import-row" data-import-row-id="${row.id}"><div class="report-row"><span>#${row.row_number} · ${row.transaction_date}</span><b>${escapeHtml(row.description || "—")}</b><strong>${money(row.amount_minor, row.currency_code)}</strong><small>${row.review_state}</small></div><div class="history-controls">${candidates}${post}${ignore}</div></div>`;
    }).join("") || `<p class="empty">Nessuna riga.</p>`;
  }
  async function refresh() {
    renderSnapshot(unwrap(await call("getSnapshot")));
    await Promise.all([refreshReports(), refreshBudgets(), refreshForecast(), refreshFxRates(), refreshScheduled(), refreshImportBatches()]);
    if (currentBatchId) await loadImportBatch(currentBatchId);
  }
  async function submit(method, form) {
    const data = Object.fromEntries(new FormData(form));
    data.placeholder = form.elements.placeholder?.checked || false;
    if (!data.payeeId) delete data.payeeId;
    const result = unwrap(await call(method, data));
    if (result.state) renderSnapshot(result.state);
    return result;
  }

  document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active")); button.classList.add("active"); document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden")); $(button.dataset.view).classList.remove("hidden"); $("view-title").textContent = button.textContent; }));
  $("account-type").addEventListener("change", (event) => $("balance-fields").classList.toggle("hidden", !["ASSET", "LIABILITY"].includes(event.target.value)));
  $("scheduled-kind").addEventListener("change", refreshScheduledCounter);
  $("scheduled-source").addEventListener("change", refreshScheduledCounter);
  $("apply-report").addEventListener("click", () => refreshReports().catch((error) => toast(error.message, true)));
  $("apply-forecast").addEventListener("click", () => refreshForecast().catch((error) => toast(error.message, true)));
  $("budget-period").addEventListener("change", () => refreshBudgets().catch((error) => toast(error.message, true)));
  $("setup-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const snapshot = unwrap(await call("setup", Object.fromEntries(new FormData(event.target)))); $("setup").classList.add("hidden"); $("app").classList.remove("hidden"); configureCurrencies(supportedCurrencies, snapshot.book.currency, snapshot.book.currency); renderSnapshot(snapshot); await refresh(); } catch (error) { toast(error.message, true); } });
  $("account-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createAccount", event.target); event.target.reset(); await Promise.all([refreshReports(), refreshBudgets()]); toast("Creato"); } catch (error) { toast(error.message, true); } });
  $("expense-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createExpense", event.target); event.target.reset(); $("payee-id").value = ""; await Promise.all([refreshReports(), refreshBudgets()]); toast("Spesa registrata"); } catch (error) { toast(error.message, true); } });
  $("budget-form").addEventListener("submit", async (event) => { event.preventDefault(); try { unwrap(await call("setBudget", Object.fromEntries(new FormData(event.target)))); const period = event.target.elements.period.value; event.target.elements.amount.value = ""; event.target.elements.period.value = period; await refreshBudgets(); toast("Budget salvato"); } catch (error) { toast(error.message, true); } });
  $("budget-list").addEventListener("click", async (event) => { const button = event.target.closest("[data-budget-delete]"); if (!button) return; try { unwrap(await call("deleteBudget", { budgetId: button.dataset.budgetDelete })); await refreshBudgets(); toast("Budget eliminato"); } catch (error) { toast(error.message, true); } });
  $("scheduled-form").addEventListener("submit", async (event) => { event.preventDefault(); try { unwrap(await call("createScheduledTransaction", Object.fromEntries(new FormData(event.target)))); const startDate = event.target.elements.startDate.value; event.target.reset(); event.target.elements.interval.value = "1"; event.target.elements.startDate.value = startDate; refreshScheduledCounter(); await Promise.all([refreshScheduled(), refreshForecast()]); toast("Programmazione creata"); } catch (error) { toast(error.message, true); } });
  $("post-due-scheduled").addEventListener("click", async () => { try { const result = unwrap(await call("postDueScheduled", { asOfDate: $("scheduled-asof").value })); if (result.state) renderSnapshot(result.state); await Promise.all([refreshScheduled(), refreshReports(), refreshBudgets(), refreshForecast()]); toast(`${result.count} scadenze registrate`); } catch (error) { toast(error.message, true); } });
  $("scheduled-list").addEventListener("click", async (event) => { const toggle = event.target.closest("[data-schedule-toggle]"); const post = event.target.closest("[data-schedule-post]"); if (!toggle && !post) return; try { if (toggle) unwrap(await call("setScheduledActive", { scheduleId: toggle.dataset.scheduleToggle, active: toggle.dataset.active === "1" })); else { const result = unwrap(await call("postDueScheduled", { scheduleId: post.dataset.schedulePost, asOfDate: $("scheduled-asof").value })); if (result.state) renderSnapshot(result.state); await Promise.all([refreshReports(), refreshBudgets()]); } await Promise.all([refreshScheduled(), refreshForecast()]); toast("Programmazione aggiornata"); } catch (error) { toast(error.message, true); } });
  $("fx-form").addEventListener("submit", async (event) => { event.preventDefault(); try { unwrap(await call("setFxRate", Object.fromEntries(new FormData(event.target)))); await Promise.all([refreshReports(), refreshBudgets(), refreshForecast(), refreshFxRates()]); toast("Tasso FX salvato"); } catch (error) { toast(error.message, true); } });
  $("import-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const file = $("import-file").files[0]; if (!file) throw new Error("Seleziona un CSV"); const data = Object.fromEntries(new FormData(event.target)); delete data["import-file"]; data.csvText = await file.text(); const result = unwrap(await call("importCsv", data)); await refreshImportBatches(); await loadImportBatch(result.batchId); toast(`Importate ${result.rowCount} righe`); } catch (error) { toast(error.message, true); } });
  $("import-batches").addEventListener("click", (event) => { const button = event.target.closest("[data-batch-id]"); if (button) loadImportBatch(button.dataset.batchId).catch((error) => toast(error.message, true)); });
  $("import-rows").addEventListener("change", (event) => { const kindSelect = event.target.closest("select[data-posting-kind-row]"); if (!kindSelect) return; const rowId = kindSelect.dataset.postingKindRow; const row = currentImportRows.get(String(rowId)); const counter = document.querySelector(`[data-counter-row="${rowId}"]`); if (!row || !counter) return; counter.innerHTML = counterOptionsForRow(row, kindSelect.value); });
  $("import-rows").addEventListener("click", async (event) => { const button = event.target.closest("button[data-action]"); if (!button) return; try { const rowId = button.dataset.rowId; if (button.dataset.action === "link") unwrap(await call("linkImportRow", { rowId, transactionId: button.dataset.transactionId })); else if (button.dataset.action === "ignore") unwrap(await call("ignoreImportRow", { rowId })); else if (button.dataset.action === "post") { const postingKind = document.querySelector(`[data-posting-kind-row="${rowId}"]`); const counter = document.querySelector(`[data-counter-row="${rowId}"]`); if (!counter?.value) throw new Error("Seleziona una contropartita compatibile"); const result = unwrap(await call("postImportRow", { rowId, postingKind: postingKind?.value, counterAccountId: counter.value })); if (result.stateSnapshot) renderSnapshot(result.stateSnapshot); await Promise.all([refreshReports(), refreshBudgets()]); } await refreshImportBatches(); if (currentBatchId) await loadImportBatch(currentBatchId); toast("Riconciliazione aggiornata"); } catch (error) { toast(error.message, true); } });
  $("load-history").addEventListener("click", async () => { try { const accountId = $("history-account").value; if (!accountId) return; const period = reportPeriod(); const history = unwrap(await call("getAccountHistory", { accountId, startDate: period.startDate, endDate: period.endDate })); $("account-history").innerHTML = `<p><b>${escapeHtml(history.name)}</b> · ${escapeHtml(history.currency)}</p>${history.points.map((point) => `<div class="report-row"><span>${point.date}</span><span>${money(point.balanceMinor, history.currency)}</span><strong>${money(point.baseValueMinor, history.baseCurrency)}</strong></div>`).join("")}`; } catch (error) { toast(error.message, true); } });
  $("refresh").addEventListener("click", () => refresh().catch((error) => toast(error.message, true)));
  $("payee-input").addEventListener("input", async (event) => { $("payee-id").value = ""; const query = event.target.value; if (!query.trim()) { $("payee-results").classList.add("hidden"); return; } try { const items = unwrap(await call("suggestPayees", query)); $("payee-results").innerHTML = items.map((item) => `<button type="button" data-id="${item.id}" data-name="${escapeHtml(item.name)}">${escapeHtml(item.name)} <small>${item.usageCount}×</small></button>`).join("") + `<button type="button" data-create="1">+ Usa “${escapeHtml(query)}”</button>`; $("payee-results").classList.remove("hidden"); } catch (error) { toast(error.message, true); } });
  $("payee-results").addEventListener("click", async (event) => { const button = event.target.closest("button"); if (!button) return; try { if (button.dataset.create) { const item = unwrap(await call("createPayee", $("payee-input").value)); $("payee-id").value = item.id; $("payee-input").value = item.name; } else { $("payee-id").value = button.dataset.id; $("payee-input").value = button.dataset.name; } $("payee-results").classList.add("hidden"); } catch (error) { toast(error.message, true); } });

  initializeDates();
  if (typeof QWebChannel === "undefined" || !window.qt?.webChannelTransport) { $("bridge-status").textContent = "Backend non disponibile"; return; }
  new QWebChannel(window.qt.webChannelTransport, async (channel) => { backend = channel.objects.backend; try { const initial = unwrap(await call("getInitialState")); configureCurrencies(initial.currencies, initial.book?.currency || null, initial.book?.currency || initial.bookCurrency); $("import-form").elements.reviewMode.value = initial.reconciliationReviewMode; $("bridge-status").textContent = "Backend connesso"; if (initial.needsSetup) $("setup").classList.remove("hidden"); else { $("app").classList.remove("hidden"); await refresh(); } } catch (error) { toast(error.message, true); } });
})();
