pragma ComponentBehavior: Bound
import QtQuick
import ".."

// One staged CSV row with backend-provided candidates and posting capabilities.
DataRow {
    id: row
    required property var modelData
    required property var app
    required property var tools
    readonly property bool resolved: ["MATCHED", "POSTED", "IGNORED"].indexOf(modelData.review_state) >= 0
    readonly property bool blocked: ["OUTSIDE_TRACKING", "TRACKING_AMBIGUOUS", "AMBIGUOUS"].indexOf(modelData.review_state) >= 0
    readonly property var kinds: Object.keys(modelData.postingCapabilities || {})
    readonly property bool canPost: !resolved && !blocked && kinds.length > 0

    title: modelData.description || "—"
    subtitle: `#${modelData.row_number} · ${modelData.transaction_date}`
    detail: modelData.review_state
    value: app.money(modelData.amount_minor, modelData.currency_code)

    function refreshCounter() {
        counter.setOptions(app.idOptions((modelData.postingCapabilities || {})[kind.value] || []))
    }

    Component.onCompleted: {
        kind.setOptions(kinds.map(item => ({ value: item, text: app.kindLabels[item] || item })))
        refreshCounter()
    }

    Repeater {
        model: row.resolved ? [] : (row.modelData.candidates || [])
        ActionButton {
            required property var modelData
            primary: false
            compact: true
            text: `Collega #${modelData.id} · ${modelData.payee_name || modelData.description || modelData.kind || "Transazione"}`
            onClicked: row.tools.rowAction("linkImportRow", { rowId: String(row.modelData.id), transactionId: String(modelData.id) }, false)
        }
    }
    ChoiceField {
        id: kind
        visible: row.canPost
        width: 160
        label: "Tipo"
        onActivated: row.refreshCounter()
    }
    ChoiceField {
        id: counter
        visible: row.canPost
        width: 240
        label: "Contropartita"
    }
    ActionButton {
        visible: row.canPost
        compact: true
        text: "Registra nel ledger"
        enabled: counter.value !== ""
        onClicked: row.tools.rowAction("postImportRow", {
            rowId: String(row.modelData.id),
            postingKind: kind.value,
            counterAccountId: counter.value
        }, true)
    }
    ActionButton {
        visible: !row.resolved
        primary: false
        compact: true
        text: "Ignora"
        onClicked: row.tools.rowAction("ignoreImportRow", { rowId: String(row.modelData.id) }, false)
    }
}
