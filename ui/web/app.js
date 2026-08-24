(() => {
  "use strict";

  const status = document.getElementById("bridge-status");

  function showState(state) {
    document.getElementById("book-currency").textContent = state.bookCurrency ?? "—";
    document.getElementById("locale").textContent = state.locale ?? "—";
    document.getElementById("schema-version").textContent = `v${state.schemaVersion ?? "—"}`;
    status.textContent = "Backend connesso";
    status.classList.add("ready");
  }

  function showBridgeFailure() {
    status.textContent = "Backend non disponibile";
    status.classList.remove("ready");
  }

  if (typeof QWebChannel === "undefined" || !window.qt?.webChannelTransport) {
    showBridgeFailure();
    return;
  }

  new QWebChannel(window.qt.webChannelTransport, (channel) => {
    const backend = channel.objects.backend;
    if (!backend) {
      showBridgeFailure();
      return;
    }
    backend.getInitialState(showState);
  });
})();
