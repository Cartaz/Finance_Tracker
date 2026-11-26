pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property string payeeId: ""
    property var payeeSuggestions: []

    function reload() {
        const postable = app.accountOptions(app.balanceAccounts(true))
        expenseAccount.setOptions(postable)
        incomeAccount.setOptions(postable)
        transferSource.setOptions(postable)
        refreshCounters()
    }
    function refreshCounters() {
        expenseCategory.setOptions(app.counterOptions(expenseAccount.value, "EXPENSE"))
        incomeCategory.setOptions(app.counterOptions(incomeAccount.value, "INCOME"))
        transferDestination.setOptions(app.counterOptions(transferSource.value, "TRANSFER"))
    }
    function resetFields(fields) {
        for (const field of fields)
            field.clear()
    }
    function submitExpense() {
        app.attempt(() => {
            const payload = {
                sourceAccountId: expenseAccount.value,
                categoryAccountId: expenseCategory.value,
                amount: expenseAmount.text,
                date: expenseDate.text,
                time: expenseTime.text,
                description: expenseDescription.text
            }
            if (page.payeeId !== "")
                payload.payeeId = page.payeeId
            const result = app.call("createExpense", payload)
            resetFields([expenseAmount, expenseTime, expenseDescription, payeeInput])
            page.payeeId = ""
            page.payeeSuggestions = []
            app.changed(result.state)
        }, "Spesa registrata")
    }
    function submitIncome() {
        app.attempt(() => {
            const result = app.call("createIncome", {
                destinationAccountId: incomeAccount.value,
                incomeAccountId: incomeCategory.value,
                amount: incomeAmount.text,
                date: incomeDate.text,
                time: incomeTime.text,
                description: incomeDescription.text
            })
            resetFields([incomeAmount, incomeTime, incomeDescription])
            app.changed(result.state)
        }, "Entrata registrata")
    }
    function submitTransfer() {
        app.attempt(() => {
            const result = app.call("createTransfer", {
                sourceAccountId: transferSource.value,
                destinationAccountId: transferDestination.value,
                amount: transferAmount.text,
                date: transferDate.text,
                time: transferTime.text,
                description: transferDescription.text
            })
            resetFields([transferAmount, transferTime, transferDescription])
            app.changed(result.state)
        }, "Giroconto registrato")
    }
    function suggestPayees(query) {
        page.payeeId = ""
        page.payeeSuggestions = query.trim() === "" ? [] : app.call("suggestPayees", query)
        payeePanel.visible = query.trim() !== ""
    }
    function choosePayee(id, name) {
        page.payeeId = String(id)
        payeeInput.text = name
        payeePanel.visible = false
    }
    function createPayee() {
        const item = app.call("createPayee", payeeInput.text)
        choosePayee(item.id, item.name)
    }

    Component.onCompleted: {
        for (const field of [expenseDate, incomeDate, transferDate])
            field.text = app.today()
    }
    Connections {
        target: page.app
        // A restored database invalidates identifiers chosen before it.
        function onSessionReset() {
            page.payeeId = ""
            page.payeeSuggestions = []
            payeeInput.clear()
            payeePanel.visible = false
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Card {
            title: "Nuova transazione"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1

            SectionTabs {
                id: tabs
                objectName: "transactionTabs"
                labels: ["Spesa", "Entrata", "Giroconto"]
            }
            StackLayout {
                Layout.fillWidth: true
                currentIndex: tabs.currentIndex

                ColumnLayout {
                    spacing: 10
                    ChoiceField {
                        id: expenseAccount
                        objectName: "expenseAccount"
                        label: "Conto"
                        onActivated: page.refreshCounters()
                    }
                    ChoiceField { id: expenseCategory; objectName: "expenseCategory"; label: "Categoria" }
                    InputField {
                        id: payeeInput
                        objectName: "payeeInput"
                        label: "Merchant"
                        placeholderText: "Inizia a scrivere…"
                        onEdited: page.app.attempt(() => page.suggestPayees(payeeInput.text))
                    }
                    Item {
                        id: payeePanel
                        visible: false
                        Layout.fillWidth: true
                        implicitHeight: payeeColumn.implicitHeight + 20
                        InsetSurface { anchors.fill: parent; radius: Theme.radiusSM }
                        ColumnLayout {
                            id: payeeColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 8
                            Repeater {
                                model: page.payeeSuggestions
                                ActionButton {
                                    required property var modelData
                                    primary: false
                                    compact: true
                                    Layout.fillWidth: true
                                    text: `${modelData.name}  ·  ${modelData.usageCount}×`
                                    onClicked: page.choosePayee(modelData.id, modelData.name)
                                }
                            }
                            ActionButton {
                                primary: false
                                compact: true
                                Layout.fillWidth: true
                                text: `+ Usa “${payeeInput.text}”`
                                onClicked: page.app.attempt(() => page.createPayee())
                            }
                        }
                    }
                    InputField { id: expenseAmount; objectName: "expenseAmount"; label: "Importo"; placeholderText: "12,30" }
                    DateField { id: expenseDate; objectName: "expenseDate"; label: "Data" }
                    TimeField { id: expenseTime; label: "Ora opzionale" }
                    InputField { id: expenseDescription; objectName: "expenseDescription"; label: "Descrizione" }
                    ActionButton {
                        objectName: "expenseSubmit"
                        text: "Registra spesa"
                        enabled: expenseAccount.value !== "" && expenseCategory.value !== ""
                        onClicked: page.submitExpense()
                    }
                }

                ColumnLayout {
                    spacing: 10
                    ChoiceField {
                        id: incomeAccount
                        objectName: "incomeAccount"
                        label: "Conto di accredito"
                        onActivated: page.refreshCounters()
                    }
                    ChoiceField { id: incomeCategory; objectName: "incomeCategory"; label: "Categoria di entrata" }
                    InputField { id: incomeAmount; objectName: "incomeAmount"; label: "Importo"; placeholderText: "1800,00" }
                    DateField { id: incomeDate; objectName: "incomeDate"; label: "Data" }
                    TimeField { id: incomeTime; label: "Ora opzionale" }
                    InputField { id: incomeDescription; objectName: "incomeDescription"; label: "Descrizione"; placeholderText: "Stipendio" }
                    ActionButton {
                        objectName: "incomeSubmit"
                        text: "Registra entrata"
                        enabled: incomeAccount.value !== "" && incomeCategory.value !== ""
                        onClicked: page.submitIncome()
                    }
                }

                ColumnLayout {
                    spacing: 10
                    Note { text: "Sposta denaro tra due conti della stessa valuta senza creare un'entrata o una spesa." }
                    ChoiceField {
                        id: transferSource
                        objectName: "transferSource"
                        label: "Da"
                        onActivated: page.refreshCounters()
                    }
                    ChoiceField { id: transferDestination; objectName: "transferDestination"; label: "A" }
                    InputField { id: transferAmount; objectName: "transferAmount"; label: "Importo"; placeholderText: "100,00" }
                    DateField { id: transferDate; objectName: "transferDate"; label: "Data" }
                    TimeField { id: transferTime; label: "Ora opzionale" }
                    InputField { id: transferDescription; objectName: "transferDescription"; label: "Descrizione" }
                    ActionButton {
                        objectName: "transferSubmit"
                        text: "Registra giroconto"
                        enabled: transferSource.value !== "" && transferDestination.value !== ""
                        onClicked: page.submitTransfer()
                    }
                }
            }
        }

        Card {
            title: "Transazioni"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Note { text: "Ultime 100 transazioni del book." }
            BoundedList {
                objectName: "transactionsList"
                maxHeight: 720
                emptyText: "Nessuna transazione."
                model: page.app.snapshot ? page.app.snapshot.transactions : []
                delegate: TransactionRow { app: page.app }
            }
        }
    }
}
