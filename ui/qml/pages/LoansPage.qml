pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property var capabilities: ({ targets: [], interestExpenseAccounts: [], rateTypes: [], amortizationTypes: [], policyCombinations: [] })
    property var loans: []
    property string selectedLoanId: ""
    property var selectedLoan: null
    property var plan: null
    property var payments: []
    property var revisions: []
    readonly property var target: capabilities.targets.find(item => String(item.liabilityAccountId) === liability.value)
    readonly property var modeLabels: ({ NEW_DISBURSEMENT: "Nuova erogazione", EXISTING_BALANCE: "Saldo già presente" })
    readonly property var rateLabels: ({ FIXED: "Fisso", VARIABLE: "Variabile" })
    readonly property var amortizationLabels: ({
        FRENCH: "Francese · rata tendenzialmente costante",
        ITALIAN: "Italiano · capitale costante",
        BULLET: "Bullet · capitale a scadenza"
    })
    readonly property var recastLabels: ({
        REDUCE_PAYMENT: "Ricalcola rata · scadenza invariata",
        REDUCE_TERM: "Mantieni rata · riduci durata"
    })

    function labelled(values, labels) {
        return (values || []).map(value => ({ value: value, text: labels[value] || value }))
    }
    function recastOptions(rateType, amortizationType) {
        const combination = (capabilities.policyCombinations || [])
            .find(item => item.rateType === rateType && item.amortizationType === amortizationType)
        return labelled(combination ? combination.recastStrategies : [], recastLabels)
    }
    function reload() {
        capabilities = app.call("getLoanCapabilities")
        liability.setOptions(capabilities.targets.map(item => ({
            value: String(item.liabilityAccountId),
            text: `${item.name} · ${item.currency}`
        })))
        interestAccount.setOptions(capabilities.interestExpenseAccounts.map(item => ({ value: String(item.id), text: item.name })))
        rateType.setOptions(labelled(capabilities.rateTypes, rateLabels))
        amortizationType.setOptions(labelled(capabilities.amortizationTypes, amortizationLabels))
        refreshTarget()
        loans = app.call("listLoans")
        const keep = loans.find(item => String(item.id) === selectedLoanId)
        if (keep)
            loadDetail(keep.id)
        else if (loans.length)
            loadDetail(loans[0].id)
        else
            clearDetail()
    }
    function refreshTarget() {
        paymentAccount.setOptions(app.idOptions(target ? target.paymentAccountIds : []))
        fundingAccount.setOptions(app.idOptions(target ? target.fundingAccountIds : []))
        mode.setOptions(labelled(target ? target.allowedModes : [], modeLabels))
        refreshRecast()
    }
    function refreshRecast() {
        recastStrategy.setOptions(recastOptions(rateType.value, amortizationType.value))
    }
    function clearDetail() {
        selectedLoanId = ""
        selectedLoan = null
        plan = null
        payments = []
        revisions = []
    }
    function loadDetail(loanId) {
        const loan = loans.find(item => String(item.id) === String(loanId))
        if (!loan) {
            clearDetail()
            return
        }
        const payload = { loanId: String(loanId) }
        selectedLoanId = String(loanId)
        selectedLoan = loan
        plan = app.call("getLoanPlan", payload)
        payments = app.call("getLoanPayments", payload)
        revisions = app.call("getLoanRateRevisions", payload)
        customRecast.setOptions(recastOptions(loan.rateType, loan.amortizationType))
        rateEffective.text = loan.nextDueDate || app.today()
    }
    function submitLoan() {
        app.attempt(() => {
            const payload = {
                name: loanName.text,
                mode: mode.value,
                liabilityAccountId: liability.value,
                paymentAccountId: paymentAccount.value,
                interestExpenseAccountId: interestAccount.value,
                rateType: rateType.value,
                amortizationType: amortizationType.value,
                recastStrategy: recastStrategy.value,
                annualRate: annualRate.text,
                termMonths: termMonths.text,
                firstDueDate: firstDueDate.text
            }
            if (mode.value === "NEW_DISBURSEMENT") {
                payload.fundingAccountId = fundingAccount.value
                payload.principal = principal.text
                payload.startDate = startDate.text
            }
            const created = app.call("createLoan", payload)
            selectedLoanId = String(created.id)
            loanName.clear()
            annualRate.clear()
            principal.clear()
            app.changed()
        }, "Prestito creato")
    }
    function postNext(loanId) {
        app.attempt(() => {
            const result = app.call("postNextLoanPayment", { loanId: String(loanId) })
            selectedLoanId = String(loanId)
            app.changed(result.state)
        }, "Rata registrata")
    }
    function postCustom() {
        app.attempt(() => {
            const result = app.call("postCustomLoanPayment", {
                loanId: selectedLoanId,
                amount: customAmount.text,
                recastStrategy: customRecast.value
            })
            customAmount.clear()
            app.changed(result.state)
        }, "Pagamento personalizzato registrato")
    }
    function saveRate() {
        app.attempt(() => {
            app.call("setLoanVariableRate", {
                loanId: selectedLoanId,
                effectiveDate: rateEffective.text,
                annualRate: rateValue.text
            })
            rateValue.clear()
            app.changed()
        }, "Tasso variabile aggiornato")
    }

    Component.onCompleted: {
        startDate.text = app.today()
        firstDueDate.text = app.monthsFromToday(1)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Card {
            title: "Nuovo prestito"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Note { text: "Il capitale residuo è sempre il saldo reale del conto debito. Il piano è una proiezione derivata dal contratto, dalla storia dei tassi e dal ledger." }
            Note {
                visible: page.capabilities.targets.length === 0
                color: Theme.accent
                text: "Per creare un prestito serve un conto di tipo Debito nella sezione Conti."
            }
            InputField { id: loanName; objectName: "loanName"; label: "Nome"; placeholderText: "Prestito personale" }
            ChoiceField { id: liability; objectName: "loanLiability"; label: "Conto debito"; onActivated: page.refreshTarget() }
            ChoiceField { id: mode; objectName: "loanMode"; label: "Modalità" }
            ChoiceField { id: paymentAccount; label: "Conto pagamenti" }
            ChoiceField { id: interestAccount; label: "Categoria interessi" }
            ChoiceField { id: rateType; label: "Tipo tasso"; onActivated: page.refreshRecast() }
            ChoiceField { id: amortizationType; label: "Ammortamento"; onActivated: page.refreshRecast() }
            ChoiceField { id: recastStrategy; label: "Dopo pagamento personalizzato" }
            InputField { id: annualRate; objectName: "loanRate"; label: "Tasso annuo iniziale %"; placeholderText: "5,25" }
            InputField {
                id: termMonths
                label: "Durata residua (mesi)"
                text: "12"
                validator: IntValidator { bottom: 1; top: 600 }
            }
            DateField { id: firstDueDate; label: "Prima rata" }
            ColumnLayout {
                visible: mode.value === "NEW_DISBURSEMENT"
                Layout.fillWidth: true
                spacing: 10
                ChoiceField { id: fundingAccount; label: "Conto di erogazione" }
                InputField { id: principal; objectName: "loanPrincipal"; label: "Capitale"; placeholderText: "10000,00" }
                DateField { id: startDate; label: "Data erogazione" }
            }
            ActionButton {
                objectName: "loanSubmit"
                text: "Crea prestito"
                enabled: !!page.target && mode.value !== "" && interestAccount.value !== ""
                onClicked: page.submitLoan()
            }
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 1
            Layout.fillWidth: true
            spacing: Theme.gap

            Card {
                title: "Prestiti"
                BoundedList {
                    objectName: "loanList"
                    maxHeight: 300
                    emptyText: "Nessun prestito configurato."
                    model: page.loans
                    delegate: DataRow {
                        required property var modelData
                        title: modelData.name
                        subtitle: `${modelData.rateType} · ${modelData.amortizationType} · ${page.app.bps(modelData.currentAnnualRateBps)} · residuo ${page.app.money(modelData.outstandingPrincipalMinor, modelData.currency)}`
                        detail: modelData.closed ? `${modelData.paidInstallments} pagamenti registrati`
                            : `Prossima ${modelData.nextDueDate} · max ${modelData.remainingInstallments} scadenze`
                        value: modelData.closed ? "ESTINTO" : page.app.money(modelData.nextPaymentMinor, modelData.currency)
                        ActionButton {
                            text: "Dettagli"
                            primary: false
                            compact: true
                            onClicked: page.app.attempt(() => page.loadDetail(modelData.id))
                        }
                        ActionButton {
                            visible: !modelData.closed
                            text: "Registra rata"
                            compact: true
                            onClicked: page.postNext(modelData.id)
                        }
                    }
                }
            }

            Card {
                title: "Piano e pagamenti"
                Note { visible: !page.selectedLoan; text: "Seleziona un prestito." }
                ColumnLayout {
                    visible: !!page.selectedLoan
                    Layout.fillWidth: true
                    spacing: 10

                    DataRow {
                        Layout.fillWidth: true
                        title: page.selectedLoan ? page.selectedLoan.name : ""
                        subtitle: page.selectedLoan ? `${page.selectedLoan.rateType} · ${page.selectedLoan.amortizationType} · ${page.selectedLoan.recastStrategy} · tasso ${page.app.bps(page.selectedLoan.currentAnnualRateBps)}` : ""
                        detail: page.selectedLoan ? "Residuo " + page.app.money(page.selectedLoan.outstandingPrincipalMinor, page.selectedLoan.currency) : ""
                        value: !page.selectedLoan ? "" : page.selectedLoan.closed ? "ESTINTO"
                            : `Prossima ${page.app.money(page.selectedLoan.nextPaymentMinor, page.selectedLoan.currency)} · ${page.selectedLoan.nextDueDate}`
                    }

                    ColumnLayout {
                        visible: !!page.selectedLoan && !page.selectedLoan.closed
                        Layout.fillWidth: true
                        spacing: 8
                        Label { text: "Pagamento personalizzato"; color: Theme.primary; font.bold: true }
                        Note { text: "Deve essere almeno pari alla prossima rata prevista. L'eccedenza è rimborso anticipato; importi inferiori richiederebbero un modello arretrati e vengono rifiutati." }
                        RowLayout {
                            Layout.fillWidth: true
                            InputField {
                                id: customAmount
                                label: "Importo"
                                placeholderText: page.selectedLoan ? page.app.money(page.selectedLoan.nextPaymentMinor, page.selectedLoan.currency) : ""
                            }
                            ChoiceField { id: customRecast; label: "Ricalcolo" }
                            ActionButton {
                                text: "Registra pagamento"
                                Layout.alignment: Qt.AlignBottom
                                onClicked: page.postCustom()
                            }
                        }
                    }

                    ColumnLayout {
                        visible: !!page.selectedLoan && page.selectedLoan.rateType === "VARIABLE" && !page.selectedLoan.closed
                        Layout.fillWidth: true
                        spacing: 8
                        Label { text: "Nuovo tasso"; color: Theme.primary; font.bold: true }
                        Note { text: "Il piano usa l'ultima revisione effettiva nota fino a una nuova revisione esplicita: non vengono previsti indici futuri." }
                        RowLayout {
                            Layout.fillWidth: true
                            DateField { id: rateEffective; label: "Effettivo dal" }
                            InputField { id: rateValue; label: "Tasso annuo %"; placeholderText: "5,25" }
                            ActionButton {
                                text: "Salva revisione"
                                Layout.alignment: Qt.AlignBottom
                                onClicked: page.saveRate()
                            }
                        }
                    }

                    Label { text: "Piano residuo"; color: Theme.primary; font.bold: true }
                    BoundedList {
                        maxHeight: 280
                        emptyText: "Nessuna rata residua."
                        model: page.plan ? page.plan.rows : []
                        delegate: DataRow {
                            required property var modelData
                            title: `#${modelData.installmentNumber} · ${modelData.dueDate}`
                            subtitle: `Capitale ${page.app.money(modelData.principalMinor, page.plan.currency)} · Interessi ${page.app.money(modelData.interestMinor, page.plan.currency)} · ${page.app.bps(modelData.annualRateBps)}`
                            value: page.app.money(modelData.paymentMinor, page.plan.currency)
                        }
                    }
                    Note { text: page.plan ? "Interessi residui previsti: " + page.app.money(page.plan.totalInterestMinor, page.plan.currency) : "" }

                    Label { text: "Storia tassi"; color: Theme.primary; font.bold: true }
                    BoundedList {
                        maxHeight: 160
                        emptyText: "Tasso fisso: nessuna revisione."
                        model: page.revisions
                        delegate: DataRow {
                            required property var modelData
                            title: modelData.effectiveDate
                            value: page.app.bps(modelData.annualRateBps)
                        }
                    }

                    Label { text: "Rate registrate"; color: Theme.primary; font.bold: true }
                    BoundedList {
                        maxHeight: 240
                        emptyText: "Nessuna rata registrata."
                        model: page.payments
                        delegate: DataRow {
                            required property var modelData
                            title: `#${modelData.installmentNumber} · ${modelData.dueDate}`
                            subtitle: `${modelData.paymentKind} · capitale ${page.app.money(modelData.principalMinor, page.plan ? page.plan.currency : "")} · interessi ${page.app.money(modelData.interestMinor, page.plan ? page.plan.currency : "")} · ${page.app.bps(modelData.annualRateBps)}`
                            value: page.app.money(modelData.paymentMinor, page.plan ? page.plan.currency : "")
                        }
                    }
                }
            }
        }
    }
}
