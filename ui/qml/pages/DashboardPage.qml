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
        report = app.call("getDashboard", {
            startDate: startDate.text,
            endDate: endDate.text,
            asOfDate: asOfDate.text
        })
    }

    Component.onCompleted: {
        startDate.text = app.monthStart()
        endDate.text = app.today()
        asOfDate.text = app.today()
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            DateField { id: startDate; label: "Dal" }
            DateField { id: endDate; label: "Al" }
            DateField { id: asOfDate; label: "Patrimonio al" }
            ActionButton {
                text: "Applica"
                Layout.alignment: Qt.AlignBottom
                onClicked: page.app.attempt(() => page.reload())
            }
        }
    }

    Card {
        warning: true
        visible: !!page.report && page.report.overview.missingFx.length > 0
        Label { text: "Reporting incompleto: tassi FX mancanti"; color: Theme.accent; font.bold: true }
        Note { text: page.report ? page.app.missingFxText(page.report.overview.missingFx) : "" }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap
        MetricCard {
            objectName: "metricNetWorth"
            label: "Patrimonio netto"
            value: page.report ? page.app.money(page.report.overview.netWorthMinor, page.currency) : "—"
        }
        MetricCard {
            label: "Entrate"
            value: page.report ? page.app.money(page.report.overview.incomeMinor, page.currency) : "—"
        }
        MetricCard {
            label: "Uscite"
            value: page.report ? page.app.money(page.report.overview.expenseMinor, page.currency) : "—"
        }
        MetricCard {
            label: "Saving rate"
            value: page.report ? page.app.bps(page.report.overview.savingRateBps) : "—"
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap

        Card {
            title: "Cash flow"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                maxHeight: 320
                emptyText: "Nessun flusso nel periodo."
                model: page.report ? page.report.cashFlow : []
                delegate: DataRow {
                    required property var modelData
                    title: modelData.period
                    subtitle: `Entrate ${page.app.money(modelData.incomeMinor, page.currency)} · Uscite ${page.app.money(modelData.expenseMinor, page.currency)}`
                    value: page.app.money(modelData.netMinor, page.currency)
                }
            }
        }
        Card {
            title: "Spese per categoria"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                maxHeight: 320
                emptyText: "Nessuna spesa nel periodo."
                model: page.report ? page.report.categories : []
                delegate: DataRow {
                    required property var modelData
                    title: modelData.path
                    subtitle: `${modelData.transactionCount} movimenti`
                    value: page.app.money(modelData.amountMinor, page.currency)
                }
            }
        }
        Card {
            title: "Merchant"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                maxHeight: 320
                emptyText: "Nessun merchant nel periodo."
                model: page.report ? page.report.merchants : []
                delegate: DataRow {
                    required property var modelData
                    title: modelData.name
                    subtitle: `${modelData.transactionCount} movimenti`
                    value: page.app.money(modelData.amountMinor, page.currency)
                }
            }
        }
        Card {
            title: "Movimenti recenti"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                maxHeight: 320
                emptyText: "Nessuna transazione."
                model: page.app.snapshot ? page.app.snapshot.transactions.slice(0, 20) : []
                delegate: TransactionRow { app: page.app }
            }
        }
    }
}
