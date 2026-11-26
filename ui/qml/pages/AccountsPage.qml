pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property var history: null
    readonly property string historyCurrency: history ? history.currency : ""
    readonly property string historyBaseCurrency: history ? history.baseCurrency : ""
    readonly property var balanceItems: app.balanceAccounts(false)
    readonly property var categoryItems: app.accounts()
        .filter(item => item.type === "EXPENSE" || item.type === "INCOME")
        .map(item => ({ item: item, path: app.categoryPath(item) }))
        .sort((a, b) => a.item.type.localeCompare(b.item.type) || a.path.localeCompare(b.path, "it"))

    function reload() {
        const firstLoad = accountCurrency.options.length === 0
        accountCurrency.setOptions(app.currencyOptions(false))
        if (firstLoad)
            accountCurrency.select(app.baseCurrency)
        historyAccount.setOptions(app.accountOptions(app.balanceAccounts(false)))
        refreshDirections()
        refreshParents()
    }
    function refreshDirections() {
        openingDirection.setOptions(accountType.value === "LIABILITY"
            ? [{ value: "NEGATIVE", text: "Debito da pagare (−)" }, { value: "POSITIVE", text: "Credito a tuo favore (+)" }]
            : [{ value: "POSITIVE", text: "Saldo disponibile (+)" }, { value: "NEGATIVE", text: "Saldo in rosso (−)" }])
        openingDirection.combo.currentIndex = 0
    }
    function refreshParents() {
        const options = [{ value: "", text: "Nessuna (categoria principale)" }]
        for (const entry of categoryItems) {
            if (entry.item.type === categoryType.value)
                options.push({ value: String(entry.item.id), text: entry.path + (entry.item.placeholder ? " · contenitore" : "") })
        }
        categoryParent.setOptions(options)
    }
    function submitAccount() {
        app.attempt(() => {
            const result = app.call("createAccount", {
                type: accountType.value,
                name: accountName.text,
                currency: accountCurrency.value,
                trackingStartDate: trackingDate.text,
                trackingStartTime: trackingTime.text,
                openingBalance: openingBalance.text,
                openingBalanceDirection: openingDirection.value,
                placeholder: accountPlaceholder.checked
            })
            accountName.clear()
            trackingTime.clear()
            openingBalance.clear()
            accountPlaceholder.checked = false
            app.changed(result.state)
        }, "Conto creato")
    }
    function submitCategory() {
        app.attempt(() => {
            const result = app.call("createAccount", {
                type: categoryType.value,
                name: categoryName.text,
                parentId: categoryParent.value,
                placeholder: categoryPlaceholder.checked
            })
            categoryName.clear()
            categoryPlaceholder.checked = false
            app.changed(result.state)
        }, "Categoria creata")
    }
    function loadHistory() {
        history = app.call("getAccountHistory", {
            accountId: historyAccount.value,
            startDate: historyStart.text,
            endDate: historyEnd.text
        })
    }

    Connections {
        target: page.app
        function onSessionReset() { page.history = null }
    }
    Component.onCompleted: {
        trackingDate.text = app.today()
        historyStart.text = app.monthStart()
        historyEnd.text = app.today()
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Card {
            title: "Nuovo elemento"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1

            SectionTabs { id: createTabs; objectName: "accountCreateTabs"; labels: ["Conti e debiti", "Categorie"] }
            StackLayout {
                Layout.fillWidth: true
                currentIndex: createTabs.currentIndex

                ColumnLayout {
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        ChoiceField {
                            id: accountType
                            objectName: "accountType"
                            label: "Tipo"
                            options: [
                                { value: "ASSET", text: "Conto / disponibilità" },
                                { value: "LIABILITY", text: "Debito / passività" }
                            ]
                            onActivated: page.refreshDirections()
                        }
                        ActionButton {
                            text: "?"
                            primary: false
                            compact: true
                            Layout.preferredWidth: 36
                            Layout.alignment: Qt.AlignBottom
                            Accessible.name: "Spiega i tipi di conto"
                            onClicked: typeHelp.visible = !typeHelp.visible
                        }
                    }
                    Note {
                        id: typeHelp
                        visible: false
                        text: "Conto / disponibilità: denaro o credito che possiedi (conto corrente, contanti, deposito).\nDebito / passività: somme che devi (carta di credito, prestito, mutuo).\nIl saldo iniziale fotografa la situazione reale quando inizi a usare Finance Tracker."
                    }
                    InputField { id: accountName; objectName: "accountName"; label: "Nome"; placeholderText: "Conto corrente" }
                    ChoiceField { id: accountCurrency; objectName: "accountCurrency"; label: "Valuta" }
                    DateField { id: trackingDate; objectName: "trackingDate"; label: "Inizio monitoraggio" }
                    TimeField { id: trackingTime; label: "Ora opzionale" }
                    InputField { id: openingBalance; objectName: "openingBalance"; label: "Saldo iniziale opzionale"; placeholderText: "2500,00" }
                    ChoiceField { id: openingDirection; objectName: "openingDirection"; label: "Tipo di saldo" }
                    Note { text: "Inserisci solo il valore assoluto: il tipo di saldo stabilisce se il conto parte sopra o sotto zero. Lascia vuoto per partire da 0." }
                    CheckField { id: accountPlaceholder; text: "Conto contenitore (non registrabile)" }
                    ActionButton { objectName: "accountSubmit"; text: "Crea conto"; onClicked: page.submitAccount() }
                }

                ColumnLayout {
                    spacing: 10
                    Note { text: "Le categorie classificano entrate e spese. Puoi inserirle sotto una categoria esistente per creare una gerarchia." }
                    ChoiceField {
                        id: categoryType
                        objectName: "categoryType"
                        label: "Tipo"
                        options: [
                            { value: "EXPENSE", text: "Categoria di spesa" },
                            { value: "INCOME", text: "Categoria di entrata" }
                        ]
                        onActivated: page.refreshParents()
                    }
                    InputField { id: categoryName; objectName: "categoryName"; label: "Nome"; placeholderText: "Alimentari" }
                    ChoiceField { id: categoryParent; objectName: "categoryParent"; label: "Categoria padre" }
                    CheckField { id: categoryPlaceholder; text: "Categoria contenitore (solo raggruppamento)" }
                    ActionButton { objectName: "categorySubmit"; text: "Crea categoria"; onClicked: page.submitCategory() }
                }
            }
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Layout.fillWidth: true
            spacing: Theme.gap

            Card {
                title: "Struttura finanziaria"
                SectionTabs { id: overviewTabs; labels: ["Conti e debiti", "Categorie"] }
                StackLayout {
                    Layout.fillWidth: true
                    currentIndex: overviewTabs.currentIndex
                    BoundedList {
                        objectName: "accountsList"
                        emptyText: "Nessun conto o debito."
                        model: page.balanceItems
                        delegate: DataRow {
                            required property var modelData
                            title: modelData.name
                            subtitle: [page.app.accountTypeLabels[modelData.type], modelData.currency,
                                       modelData.placeholder ? "contenitore" : ""].filter(item => !!item).join(" · ")
                            value: modelData.balanceMinor === null ? "" : page.app.money(modelData.balanceMinor, modelData.currency)
                        }
                    }
                    BoundedList {
                        emptyText: "Nessuna categoria."
                        model: page.categoryItems
                        delegate: DataRow {
                            required property var modelData
                            title: modelData.path
                            subtitle: page.app.accountTypeLabels[modelData.item.type] + (modelData.item.placeholder ? " · contenitore" : "")
                        }
                    }
                }
            }

            Card {
                title: "Storico conto"
                ChoiceField { id: historyAccount; label: "Conto" }
                RowLayout {
                    Layout.fillWidth: true
                    DateField { id: historyStart; label: "Dal" }
                    DateField { id: historyEnd; label: "Al" }
                    ActionButton {
                        text: "Carica"
                        Layout.alignment: Qt.AlignBottom
                        enabled: historyAccount.value !== ""
                        onClicked: page.app.attempt(() => page.loadHistory())
                    }
                }
                Label {
                    textFormat: Text.PlainText
                    visible: !!page.history
                    text: page.history ? `${page.history.name} · ${page.historyCurrency}` : ""
                    color: Theme.primary
                    font.bold: true
                }
                BoundedList {
                    visible: !!page.history
                    emptyText: "Nessun movimento nel periodo."
                    model: page.history ? page.history.points : []
                    delegate: DataRow {
                        required property var modelData
                        title: modelData.date
                        detail: page.app.money(modelData.balanceMinor, page.historyCurrency)
                        value: page.app.money(modelData.baseValueMinor, page.historyBaseCurrency)
                    }
                }
            }
        }
    }
}
