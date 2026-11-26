pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property var schedules: []
    readonly property var frequencyLabels: ({ DAILY: "Giornaliera", WEEKLY: "Settimanale", MONTHLY: "Mensile", YEARLY: "Annuale" })

    function reload() {
        source.setOptions(app.accountOptions(app.balanceAccounts(true)))
        refreshCounter()
        schedules = app.call("listScheduledTransactions")
    }
    function refreshCounter() {
        counter.setOptions(app.counterOptions(source.value, kind.value))
    }
    function submit() {
        app.attempt(() => {
            app.call("createScheduledTransaction", {
                kind: kind.value,
                sourceAccountId: source.value,
                counterAccountId: counter.value,
                amount: amount.text,
                frequency: frequency.value,
                interval: interval.text,
                startDate: startDate.text,
                endDate: endDate.text,
                description: description.text
            })
            amount.clear()
            endDate.clear()
            description.clear()
            interval.text = "1"
            app.changed()
        }, "Programmazione creata")
    }
    function postDue(scheduleId) {
        app.attempt(() => {
            const payload = { asOfDate: asOf.text }
            if (scheduleId !== undefined)
                payload.scheduleId = String(scheduleId)
            const result = app.call("postDueScheduled", payload)
            app.changed(result.state)
            app.toast(`${result.count} scadenze registrate`, false)
        })
    }
    function toggle(item) {
        app.attempt(() => {
            app.call("setScheduledActive", { scheduleId: String(item.id), active: !item.active })
            app.changed()
        }, "Programmazione aggiornata")
    }

    Component.onCompleted: {
        startDate.text = app.today()
        asOf.text = app.today()
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Card {
            title: "Nuova transazione programmata"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Note { text: "Il template non modifica il ledger finché una scadenza non viene registrata." }
            ChoiceField {
                id: kind
                objectName: "scheduledKind"
                label: "Tipo"
                options: [
                    { value: "EXPENSE", text: "Spesa" },
                    { value: "INCOME", text: "Entrata" },
                    { value: "REFUND", text: "Rimborso" },
                    { value: "TRANSFER", text: "Giroconto" }
                ]
                onActivated: page.refreshCounter()
            }
            ChoiceField { id: source; objectName: "scheduledSource"; label: "Conto"; onActivated: page.refreshCounter() }
            ChoiceField { id: counter; objectName: "scheduledCounter"; label: "Contropartita" }
            InputField { id: amount; objectName: "scheduledAmount"; label: "Importo"; placeholderText: "12,30" }
            ChoiceField {
                id: frequency
                label: "Frequenza"
                options: [
                    { value: "MONTHLY", text: "Mensile" },
                    { value: "WEEKLY", text: "Settimanale" },
                    { value: "DAILY", text: "Giornaliera" },
                    { value: "YEARLY", text: "Annuale" }
                ]
            }
            InputField { id: interval; label: "Ogni"; text: "1"; validator: IntValidator { bottom: 1; top: 365 } }
            DateField { id: startDate; objectName: "scheduledStart"; label: "Prima scadenza" }
            DateField { id: endDate; label: "Fine opzionale" }
            InputField { id: description; objectName: "scheduledDescription"; label: "Descrizione" }
            ActionButton {
                objectName: "scheduledSubmit"
                text: "Crea programmazione"
                enabled: source.value !== "" && counter.value !== ""
                onClicked: page.submit()
            }
        }

        Card {
            title: "Scadenze"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            RowLayout {
                Layout.fillWidth: true
                DateField { id: asOf; objectName: "scheduledAsOf"; label: "Registra fino al" }
                ActionButton {
                    objectName: "postDueScheduled"
                    text: "Registra scadenze dovute"
                    Layout.alignment: Qt.AlignBottom
                    onClicked: page.postDue()
                }
            }
            BoundedList {
                objectName: "scheduledList"
                maxHeight: 640
                emptyText: "Nessuna transazione programmata."
                model: page.schedules
                delegate: DataRow {
                    required property var modelData
                    title: modelData.description || page.app.kindLabels[modelData.kind] || modelData.kind
                    subtitle: `${modelData.sourceAccountName} → ${modelData.counterAccountName} · ${page.frequencyLabels[modelData.frequency] || modelData.frequency} × ${modelData.interval}`
                    detail: `prossima ${modelData.nextDueDate}${modelData.endDate ? " · fine " + modelData.endDate : ""} · ${modelData.active ? "Attiva" : "In pausa"}`
                    value: page.app.money(modelData.amountMinor, modelData.currency)
                    ActionButton {
                        text: modelData.active ? "Pausa" : "Riattiva"
                        primary: false
                        compact: true
                        onClicked: page.toggle(modelData)
                    }
                    ActionButton {
                        text: "Registra dovute"
                        compact: true
                        enabled: modelData.active
                        onClicked: page.postDue(modelData.id)
                    }
                }
            }
        }
    }
}
