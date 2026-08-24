(() => {
  "use strict";
  let backend = null;
  let state = null;
  const $ = (id) => document.getElementById(id);
  const call = (method, ...args) => new Promise((resolve) => backend[method](...args, resolve));
  const toast = (message, bad = false) => { $("toast").textContent = message; $("toast").className = bad ? "show bad" : "show"; setTimeout(() => $("toast").className = "", 2800); };
  const unwrap = (result) => { if (!result?.ok) { throw new Error(result?.error?.message || "Operazione fallita"); } return result.data; };
  const money = (minor, currency = "EUR") => new Intl.NumberFormat("it-IT", { style: "currency", currency }).format((minor || 0) / 100);

  function render(snapshot) {
    state = snapshot;
    $("book-name").textContent = snapshot.book.name.toUpperCase();
    const balanceAccounts = snapshot.accounts.filter((a) => ["ASSET", "LIABILITY"].includes(a.type));
    const net = balanceAccounts.reduce((sum, a) => sum + (a.balanceMinor || 0), 0);
    $("metrics").innerHTML = `<article class="card metric"><span>Patrimonio contabile</span><strong>${money(net, snapshot.book.currency)}</strong></article><article class="card metric"><span>Conti</span><strong>${balanceAccounts.length}</strong></article><article class="card metric"><span>Transazioni</span><strong>${snapshot.transactions.length}</strong></article>`;
    const txRows = snapshot.transactions.map((t) => `<div class="row"><span>${t.transaction_date}</span><b>${escapeHtml(t.payee_name || t.description || t.kind)}</b><small>${t.kind}</small></div>`).join("") || `<p class="empty">Nessuna transazione.</p>`;
    $("recent").innerHTML = txRows;
    $("transactions-list").innerHTML = txRows;
    $("accounts-list").innerHTML = snapshot.accounts.map((a) => `<div class="row"><b>${escapeHtml(a.name)}</b><small>${a.type}${a.currency ? ` · ${a.currency}` : ""}</small><span>${a.balanceMinor == null ? "" : money(a.balanceMinor, a.currency)}</span></div>`).join("") || `<p class="empty">Crea il primo conto.</p>`;
    $("expense-account").innerHTML = balanceAccounts.filter((a) => !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.currency}</option>`).join("");
    $("expense-category").innerHTML = snapshot.accounts.filter((a) => a.type === "EXPENSE" && !a.placeholder).map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
  }

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  async function refresh() { render(unwrap(await call("getSnapshot"))); }
  async function submit(method, form) { const data = Object.fromEntries(new FormData(form)); data.placeholder = form.elements.placeholder?.checked || false; if (!data.payeeId) delete data.payeeId; const result = unwrap(await call(method, data)); if (result.state) render(result.state); return result; }

  document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active")); button.classList.add("active"); document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden")); $(button.dataset.view).classList.remove("hidden"); $("view-title").textContent = button.textContent; }));
  $("account-type").addEventListener("change", (event) => $("balance-fields").classList.toggle("hidden", !["ASSET", "LIABILITY"].includes(event.target.value)));
  $("setup-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const snapshot = unwrap(await call("setup", Object.fromEntries(new FormData(event.target)))); $("setup").classList.add("hidden"); $("app").classList.remove("hidden"); render(snapshot); } catch (error) { toast(error.message, true); } });
  $("account-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createAccount", event.target); event.target.reset(); toast("Creato"); } catch (error) { toast(error.message, true); } });
  $("expense-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await submit("createExpense", event.target); event.target.reset(); $("payee-id").value = ""; toast("Spesa registrata"); } catch (error) { toast(error.message, true); } });
  $("refresh").addEventListener("click", () => refresh().catch((error) => toast(error.message, true)));
  $("payee-input").addEventListener("input", async (event) => { $("payee-id").value = ""; const query = event.target.value; if (!query.trim()) { $("payee-results").classList.add("hidden"); return; } try { const items = unwrap(await call("suggestPayees", query)); $("payee-results").innerHTML = items.map((item) => `<button type="button" data-id="${item.id}" data-name="${escapeHtml(item.name)}">${escapeHtml(item.name)} <small>${item.usageCount}×</small></button>`).join("") + `<button type="button" data-create="1">+ Usa “${escapeHtml(query)}”</button>`; $("payee-results").classList.remove("hidden"); } catch (error) { toast(error.message, true); } });
  $("payee-results").addEventListener("click", async (event) => { const button = event.target.closest("button"); if (!button) return; try { if (button.dataset.create) { const item = unwrap(await call("createPayee", $("payee-input").value)); $("payee-id").value = item.id; $("payee-input").value = item.name; } else { $("payee-id").value = button.dataset.id; $("payee-input").value = button.dataset.name; } $("payee-results").classList.add("hidden"); } catch (error) { toast(error.message, true); } });

  if (typeof QWebChannel === "undefined" || !window.qt?.webChannelTransport) { $("bridge-status").textContent = "Backend non disponibile"; return; }
  new QWebChannel(window.qt.webChannelTransport, async (channel) => { backend = channel.objects.backend; try { const initial = unwrap(await call("getInitialState")); $("bridge-status").textContent = "Backend connesso"; if (initial.needsSetup) { $("setup").classList.remove("hidden"); } else { $("app").classList.remove("hidden"); await refresh(); } } catch (error) { toast(error.message, true); } });
})();