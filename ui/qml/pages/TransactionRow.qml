pragma ComponentBehavior: Bound
import QtQuick
import ".."

DataRow {
    required property var modelData
    required property var app
    title: modelData.payee_name || app.kindLabels[modelData.kind] || modelData.kind
    subtitle: [modelData.description, app.transactionFlow(modelData)].filter(item => !!item).join(" · ")
    detail: `${modelData.transaction_date} · ${app.kindLabels[modelData.kind] || modelData.kind}`
    value: app.transactionAmount(modelData)
}
