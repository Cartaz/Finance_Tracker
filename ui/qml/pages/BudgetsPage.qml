pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property var report: null
    readonly property string currency: report ? report.baseCurrency : ""

    function reload() {
        report = app.call("getBudgetStatus", { period: period.text })
        category.setOptions((report.targets || []).map(item => ({
            value: String(item.categoryAccountId),
            text: item.categoryPath + (item.placeholder ? " · gruppo" : "") + (item.hasBudget ? " · budget esistente" : "")
        })))
    }
    function remainingText(item) {
        if (item.remainingMinor == null)
            return "FX mancante"
        const formatted = app.money(item.remainingMinor, currency)
        return item.overBudget ? "Oltre di " + formatted.replace(/^−/, "") : "Residuo " + formatted
    }
    function submit() {
        app.attempt(() => {
            app.call("setBudget", { period: period.text, categoryAccountId: category.value, amount: amount.text })
            amount.clear()
            page.reload()
        }, "Budget salvato")
    }
    function remove(budgetId) {
        app.attempt(() => {
            app.call("deleteBudget", { budgetId: String(budgetId) })
            page.reload()
        }, "Budget eliminato")
    }

    Component.onCompleted: period.text = app.currentMonth()

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Card {
            title: "Budget mensile"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Note { text: "Gli importi sono nella valuta base del book. Un budget su una categoria contenitore include tutte le sue sottocategorie." }
            DateField {
                id: period
                objectName: "budgetPeriod"
                monthOnly: true
                label: "Mese"
                onAccepted: page.app.attempt(() => page.reload())
            }
            ChoiceField { id: category; objectName: "budgetCategory"; label: "Categoria" }
            InputField { id: amount; objectName: "budgetAmount"; label: "Importo"; placeholderText: "300,00" }
            RowLayout {
                ActionButton {
                    objectName: "budgetSubmit"
                    text: "Salva budget"
                    enabled: category.value !== ""
                    onClicked: page.submit()
                }
                ActionButton {
                    text: "Mostra mese"
                    primary: false
                    onClicked: page.app.attempt(() => page.reload())
                }
            }
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Layout.fillWidth: true
            spacing: Theme.gap

            Card {
                warning: true
                visible: !!page.report && page.report.missingFx.length > 0
                Label { text: "Budget incompleto: tassi FX mancanti"; color: Theme.accent; font.bold: true }
                Note { text: page.report ? page.app.missingFxText(page.report.missingFx) : "" }
            }
            Card {
                title: "Stato del mese"
                DataRow {
                    Layout.fillWidth: true
                    title: page.report ? page.report.period : ""
                    subtitle: page.report ? `Budget ${page.app.money(page.report.totalBudgetMinor, page.currency)} · Speso ${page.app.money(page.report.totalSpentMinor, page.currency)}` : ""
                    value: page.report ? "Residuo " + page.app.money(page.report.totalRemainingMinor, page.currency) : ""
                }
                BoundedList {
                    objectName: "budgetList"
                    emptyText: "Nessun budget per questo mese."
                    model: page.report ? page.report.budgets : []
                    delegate: DataRow {
                        id: budgetRow
                        required property var modelData
                        required property int index
                        objectName: "budgetRow-" + index
                        title: modelData.categoryPath
                        subtitle: `Utilizzo ${page.app.bps(modelData.usageBps)} · ${page.app.money(modelData.spentMinor, page.currency)} / ${page.app.money(modelData.amountMinor, page.currency)}`
                        value: page.remainingText(modelData)
                        valueColor: modelData.overBudget ? Theme.danger : Theme.primary
                        ActionButton {
                            text: "Elimina"
                            primary: false
                            compact: true
                            onClicked: page.remove(budgetRow.modelData.id)
                        }
                    }
                }
            }
        }
    }
}
