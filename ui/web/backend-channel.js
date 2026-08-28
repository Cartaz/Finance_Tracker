(() => {
  "use strict";

  const QWebChannelImpl = window.QWebChannel;
  if (typeof QWebChannelImpl === "undefined") return;

  window.QWebChannel = function FinanceTrackerQWebChannel(transport, callback) {
    return new QWebChannelImpl(transport, (channel) => {
      window.financeTrackerBackend = channel.objects.backend;
      window.dispatchEvent(new Event("finance-backend-ready"));
      callback(channel);
    });
  };
  window.QWebChannel.prototype = QWebChannelImpl.prototype;

  const manualTransactions = document.createElement("script");
  manualTransactions.src = "manual-transactions.js";
  manualTransactions.async = false;
  document.head.appendChild(manualTransactions);
})();
