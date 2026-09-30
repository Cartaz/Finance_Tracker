from __future__ import annotations

import json

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.backup_controller import BackupController
from core.backup_service import BackupService
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.backup_task_manager import BackupTaskManager
from ui.bridge import Bridge
from ui.window import MainWindow

_WORKFLOWS = r"""
window.auditResult = {done: false};
(async () => {
    const el = id => document.getElementById(id);
    const waitFor = async predicate => {
        const deadline = Date.now() + 15000;
        while (!predicate()) {
            if (Date.now() > deadline) throw new Error('UI timeout: ' + el('toast').textContent);
            await new Promise(resolve => setTimeout(resolve, 20));
        }
    };
    await waitFor(() => window.financeTrackerBackend && el('bridge-status').textContent === 'Backend connesso');
    const call = (method, data) => new Promise(resolve => window.financeTrackerBackend[method](data, resolve));
    const submit = async (id, values, expectedToast) => {
        const form = el(id);
        for (const [key, value] of Object.entries(values)) {
            form.elements[key].value = value;
            form.elements[key].dispatchEvent(new Event('change', {bubbles: true}));
        }
        el('toast').textContent = '';
        form.requestSubmit();
        await waitFor(() => el('toast').textContent === expectedToast || el('toast').classList.contains('bad'));
        if (el('toast').classList.contains('bad')) throw new Error(id + ': ' + el('toast').textContent);
    };
    const setup = el('setup-form');
    setup.elements.userName.value = 'Audit'; setup.elements.bookName.value = 'UI audit';
    setup.elements.currency.value = 'EUR'; setup.requestSubmit();
    await waitFor(() => !el('app').classList.contains('hidden') && el('metrics').children.length > 0);
    document.querySelector('[data-view="accounts"]').click();
    await submit('account-form', {type:'ASSET', name:'Bank', currency:'EUR', trackingStartDate:'2026-01-01', openingBalance:'1000'}, 'Conto creato');
    await submit('account-form', {type:'ASSET', name:'Cash', currency:'EUR', trackingStartDate:'2026-01-01'}, 'Conto creato');
    el('account-create-category-tab').click();
    await submit('category-form', {type:'EXPENSE', name:'Food'}, 'Categoria creata');
    await submit('category-form', {type:'INCOME', name:'Salary'}, 'Categoria creata');
    document.querySelector('[data-view="transactions"]').click();
    await waitFor(() => el('income-category').options.length > 0 && el('transfer-destination').options.length > 0);
    await submit('expense-form', {amount:'10', date:'2026-09-30', description:'UI expense'}, 'Spesa registrata');
    el('transaction-income-tab').click();
    await submit('income-form', {amount:'100', date:'2026-09-30', description:'UI income'}, 'Entrata registrata');
    el('transaction-transfer-tab').click();
    await submit('transfer-form', {amount:'20', date:'2026-09-30', description:'UI transfer'}, 'Giroconto registrato');
    const snapshot = await new Promise(resolve => window.financeTrackerBackend.getSnapshot(resolve));
    if (!snapshot.ok || snapshot.data.transactions.length !== 4) throw new Error('Incorrect posted transaction count');
    const accountBalances = snapshot.data.accounts.filter(a => a.type === 'ASSET').map(a => a.balanceMinor);
    if (accountBalances.join(',') !== '107000,2000') throw new Error('Incorrect balances: ' + accountBalances);
    document.querySelector('[data-view="tools"]').click();
    el('tools-reconciliation-tab').click();
    const csv = new File(['date,amount,externalid\n2026-09-30,-5,ui-csv\n'], 'audit.csv', {type:'text/csv'});
    const transfer = new DataTransfer(); transfer.items.add(csv); el('import-file').files = transfer.files;
    await submit('import-form', {sourceName:'Audit CSV', reviewMode:'FULL_REVIEW'}, 'Importate 1 righe');
    if (document.querySelectorAll('.import-row').length !== 1) throw new Error('CSV row not rendered');
    window.auditResult = {done:true, ok:true, transactions:snapshot.data.transactions.length, accountBalances};
})().catch(error => {window.auditResult = {done:true, ok:false, message:error.message};});
"""


def test_first_run_forms_post_exact_balances_and_import_csv(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "ui.db")
    database.migrate()
    controller = AppController(
        database,
        Settings(),
        AccountService(database),
        LedgerService(database),
        BookService(database),
        PayeeService(database),
    )
    tasks = BackupTaskManager(
        BackupController(BackupService(database, tmp_path / "backups")),
        controller.error_payload,
    )
    bridge = Bridge(controller, tasks)
    window = MainWindow(bridge, tasks)
    window.show()
    results = []
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)

    def inspected(raw):
        if raw:
            result = json.loads(raw)
            if result.get("done"):
                results.append(result)
                loop.quit()

    poll.timeout.connect(
        lambda: window._page.runJavaScript(
            "JSON.stringify(window.auditResult || {})", inspected
        )
    )
    window._view.loadFinished.connect(
        lambda ok: window._page.runJavaScript(_WORKFLOWS) if ok else loop.quit()
    )
    poll.start(50)
    timeout.start(45_000)
    try:
        loop.exec()
        assert results, "Frontend workflow did not complete"
        assert results[0]["ok"], results[0]
        database.integrity_check()
        database.close()
        database.open()
        assert controller.snapshot()["accounts"][0]["balanceMinor"] == "107000"
    finally:
        poll.stop()
        timeout.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        database.close()
