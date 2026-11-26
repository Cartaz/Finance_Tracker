import QtQuick
import ".."

DataRow {
    id: row
    required property var modelData
    required property var app
    // Corrections are offered only where the full ledger list is shown.
    property bool withActions: false
    // An untimed tracking start cannot be reversed on the same date: the
    // user picks a later one instead.
    readonly property bool needsReversalDate: modelData.reversalBlocker === "BOUNDARY"

    function reverse() {
        // Capture now: the row may be rebuilt while the dialog is open.
        const shell = app
        const transactionId = String(modelData.id)
        if (needsReversalDate) {
            shell.prompt("Storna", "Data dello storno (AAAA-MM-GG, successiva all'inizio del monitoraggio)", shell.today(),
                chosen => shell.attempt(() => {
                    const result = shell.call("reverseTransaction", { transactionId: transactionId, date: chosen })
                    shell.changed(result.state)
                }, "Transazione stornata"))
            return
        }
        shell.confirm(
            "Stornare questa transazione? Verrà registrata una transazione uguale e contraria alla stessa data; l'originale resta nello storico.",
            () => shell.attempt(() => {
                const result = shell.call("reverseTransaction", { transactionId: transactionId })
                shell.changed(result.state)
            }, "Transazione stornata"))
    }

    title: modelData.payee_name || app.kindLabels[modelData.kind] || modelData.kind
    subtitle: [modelData.description, app.transactionFlow(modelData)].filter(item => !!item).join(" · ")
    detail: `${modelData.transaction_date} · ${app.kindLabels[modelData.kind] || modelData.kind}`
        + (modelData.reversalBlocker === "REVERSED" ? " · stornata" : "")
    value: app.transactionAmount(modelData)
    showActions: withActions && (modelData.reversible || needsReversalDate)
    valueColor: modelData.reversalBlocker === "REVERSED" ? Theme.muted : Theme.primary

    ActionButton {
        visible: row.withActions && (row.modelData.reversible || row.needsReversalDate)
        objectName: row.withActions ? "reverse-" + row.modelData.id : ""
        text: row.needsReversalDate ? "Storna…" : "Storna"
        primary: false
        compact: true
        onClicked: row.reverse()
    }
}
