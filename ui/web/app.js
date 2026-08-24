(() => {
  "use strict";
  let backend = null;
  let state = null;
  let currencySpecs = new Map();
  let supportedCurrencies = [];
  const $ = (id) => document.getElementById(id);
  const call = (method, ...args) => new Promise((resolve) => backend[method](...args, resolve));
  const toast = (message, bad = false) => { $("toast").textContent = message; $("toast").className = bad ? "show bad" : "show"; setTimeout(() => $("toast").className = "", 2800); };
  const unwrap = (result) => { if (!result?.ok) throw new Error(result?.error?.message || "Operazione fallita"); return result.data; };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
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

  function initializeDates() {
    const now = new Date();
    $("report-asof").value = localDate(now);
    $("report-end").value = localDate(now);
    $("report-start").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
    $("fx-form").elements.date.value = localDate(now);
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

  async function refreshReports() { renderDashboard(unwrap(await call("getDashboard", reportPeriod()))); }
  async function refreshFxRates() {
    const items = unwrap(await call("listFxRates"));
    $("fx-rates").innerHTML = items.map((item) => `<div class="mini-row"><span>${item.date}</span><b>${escapeHtml(item.currency)}</b><span>${escapeHtml(item.rate)}</span></div>`).join("") || `<p class="empty">Nessun tasso salvato.</p>`;
  }
  async function refresh() {
    renderSnapshot(unwrap(await call("getSnapshot")));
    await Promise.all([refreshReports(), refreshFxRates()]);
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
  $("apply-report").addEventListener("click", () => refreshReports().catch((error) => toast(error.message, true)));
  $("setup-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const snapshot = unwrap(await call("setup", Object.fromEntries(new FormData(event.target)))); $("setup").classList.add("hidden"); $("app").classList.remove("hidden"); configureCurrencies(supportedCurrencies, snapshot.book.currency, snapshot.book.currency); renderSnapshot(snapshot); await refresh(); } catch (error) { toast(error.message, true); } });
  $("account-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createAccount", event.target); event.target.reset(); await refreshReports(); toast("Creato"); } catch (error) { toast(error.message, true); } });
  $("expense-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createExpense", event.target); event.target.reset(); $("payee-id").value = ""; await refreshReports(); toast("Spesa registrata"); } catch (error) { toast(error.message, true); } });
  $("fx-form").addEventListener("submit", async (event) => { event.preventDefault(); try { unwrap(await call("setFxRate", Object.fromEntries(new FormData(event.target)))); await Promise.all([refreshReports(), refreshFxRates()]); toast("Tasso FX salvato"); } catch (error) { toast(error.message, true); } });
  $("load-history").addEventListener("click", async () => { try { const accountId = $("history-account").value; if (!accountId) return; const period = reportPeriod(); const history = unwrap(await call("getAccountHistory", { accountId, startDate: period.startDate, endDate: period.endDate })); $("account-history").innerHTML = `<p><b>${escapeHtml(history.name)}</b> · ${escapeHtml(history.currency)}</p>${history.points.map((point) => `<div class="report-row"><span>${point.date}</span><span>${money(point.balanceMinor, history.currency)}</span><strong>${money(point.baseValueMinor, history.baseCurrency)}</strong></div>`).join("")}`; } catch (error) { toast(error.message, true); } });
  $("refresh").addEventListener("click", () => refresh().catch((error) => toast(error.message, true)));
  $("payee-input").addEventListener("input", async (event) => { $("payee-id").value = ""; const query = event.target.value; if (!query.trim()) { $("payee-results").classList.add("hidden"); return; } try { const items = unwrap(await call("suggestPayees", query)); $("payee-results").innerHTML = items.map((item) => `<button type="button" data-id="${item.id}" data-name="${escapeHtml(item.name)}">${escapeHtml(item.name)} <small>${item.usageCount}×</small></button>`).join("") + `<button type="button" data-create="1">+ Usa “${escapeHtml(query)}”</button>`; $("payee-results").classList.remove("hidden"); } catch (error) { toast(error.message, true); } });
  $("payee-results").addEventListener("click", async (event) => { const button = event.target.closest("button"); if (!button) return; try { if (button.dataset.create) { const item = unwrap(await call("createPayee", $("payee-input").value)); $("payee-id").value = item.id; $("payee-input").value = item.name; } else { $("payee-id").value = button.dataset.id; $("payee-input").value = button.dataset.name; } $("payee-results").classList.add("hidden"); } catch (error) { toast(error.message, true); } });

  initializeDates();
  if (typeof QWebChannel === "undefined" || !window.qt?.webChannelTransport) { $("bridge-status").textContent = "Backend non disponibile"; return; }
  new QWebChannel(window.qt.webChannelTransport, async (channel) => { backend = channel.objects.backend; try { const initial = unwrap(await call("getInitialState")); configureCurrencies(initial.currencies, initial.book?.currency || null, initial.book?.currency || initial.bookCurrency); $("bridge-status").textContent = "Backend connesso"; if (initial.needsSetup) $("setup").classList.remove("hidden"); else { $("app").classList.remove("hidden"); await refresh(); } } catch (error) { toast(error.message, true); } });
})();
