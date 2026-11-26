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
        report = app.call("getForecast", {
            startDate: startDate.text,
            endDate: endDate.text,
            granularity: granularity.value
        })
    }
    function occurrenceValue(item) {
        return item.direction === "TRANSFER" ? app.money(item.amountMinor, item.currency) : app.money(item.baseAmountMinor, currency)
    }

    Component.onCompleted: {
        startDate.text = app.today()
        endDate.text = app.monthsFromToday(6)
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            DateField { id: startDate; label: "Dal" }
            DateField { id: endDate; label: "Al" }
            ChoiceField {
                id: granularity
                label: "Raggruppa"
                options: [
                    { value: "MONTH", text: "Mese" },
                    { value: "DAY", text: "Giorno" },
                    { value: "YEAR", text: "Anno" }
                ]
            }
            ActionButton {
                text: "Calcola"
                Layout.alignment: Qt.AlignBottom
                onClicked: page.app.attempt(() => page.reload())
            }
        }
        Note {
            text: "Proiezione deterministica delle transazioni programmate attive e delle rate prestito contrattualmente note. I trasferimenti e la quota capitale delle rate sono neutri sul flusso netto del book; gli interessi sono il costo previsto. Per le valute estere ogni scadenza usa l'ultimo tasso FX noto alla sua data: il cambio futuro non viene previsto."
        }
    }

    Card {
        warning: true
        visible: !!page.report && page.report.missingFx.length > 0
        Label { text: "Forecast incompleto: tassi FX mancanti"; color: Theme.accent; font.bold: true }
        Note { text: page.report ? page.app.missingFxText(page.report.missingFx) : "" }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap
        MetricCard { label: "Entrate previste"; value: page.report ? page.app.money(page.report.totalInflowMinor, page.currency) : "—" }
        MetricCard { label: "Uscite previste"; value: page.report ? page.app.money(page.report.totalOutflowMinor, page.currency) : "—" }
        MetricCard { label: "Netto previsto"; value: page.report ? page.app.money(page.report.totalNetMinor, page.currency) : "—" }
        MetricCard { label: "Occorrenze"; value: page.report ? `${page.report.occurrenceCount} · ${page.report.transferCount} trasferimenti` : "—" }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap
        Card {
            title: "Flussi previsti"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                emptyText: "Nessun flusso programmato nel periodo."
                model: page.report ? page.report.buckets : []
                delegate: DataRow {
                    required property var modelData
                    title: modelData.period
                    subtitle: `Entrate ${page.app.money(modelData.inflowMinor, page.currency)} · Uscite ${page.app.money(modelData.outflowMinor, page.currency)}`
                    detail: `${modelData.occurrenceCount} occorrenze · ${modelData.transferCount} transfer`
                    value: page.app.money(modelData.netMinor, page.currency)
                }
            }
        }
        Card {
            title: "Occorrenze previste"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            BoundedList {
                objectName: "forecastOccurrences"
                emptyText: "Nessuna occorrenza prevista."
                model: page.report ? page.report.occurrences : []
                delegate: DataRow {
                    required property var modelData
                    title: modelData.description || modelData.kind
                    subtitle: modelData.kind + (modelData.currency !== page.currency ? ` · origine ${page.app.money(modelData.amountMinor, modelData.currency)}` : "")
                    detail: `${modelData.dueDate} · ${modelData.direction}`
                    value: page.occurrenceValue(modelData)
                }
            }
        }
    }
}
