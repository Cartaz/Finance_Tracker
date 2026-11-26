import QtQuick
import ".."

DataRow {
    id: row
    required property var modelData
    required property var app
    // Corrections are offered only where the full ledger list is shown.
    property bool withActions: false

    function reverse() {
        app.confirm(
            "Stornare questa transazione? Verrà registrata una transazione uguale e contraria alla stessa data; l'originale resta nello storico.",
            () => app.attempt(() => {
                const result = app.call("reverseTransaction", { transactionId: String(row.modelData.id) })
                app.changed(result.state)
            }, "Transazione stornata"))
    }

    title: modelData.payee_name || app.kindLabels[modelData.kind] || modelData.kind
    subtitle: [modelData.description, app.transactionFlow(modelData)].filter(item => !!item).join(" · ")
    detail: `${modelData.transaction_date} · ${app.kindLabels[modelData.kind] || modelData.kind}`
        + (modelData.reversalBlocker === "REVERSED" ? " · stornata" : "")
    value: app.transactionAmount(modelData)
    valueColor: modelData.reversalBlocker === "REVERSED" ? Theme.muted : Theme.primary

    ActionButton {
        visible: row.withActions && row.modelData.reversible
        objectName: "reverse-" + row.modelData.id
        text: "Storna"
        primary: false
        compact: true
        onClicked: row.reverse()
    }
}
