pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

PageScaffold {
    id: page
    property var backups: []
    property var batches: []
    property var rates: []
    property string batchId: ""
    property int pageIndex: 0
    property var rows: []
    property bool hasNextPage: false
    readonly property int pageSize: 100

    property bool defaultsPending: true

    function reload() {
        if (defaultsPending) {
            reviewMode.select(app.initial.reconciliationReviewMode)
            defaultsPending = false
        }
        backups = app.call("listBackups")
        importAccount.setOptions(app.accountOptions(app.balanceAccounts(true)))
        fxCurrency.setOptions(app.currencyOptions(true))
        rates = app.call("listFxRates")
        batches = app.call("listImportBatches")
        if (batchId !== "")
            loadBatch(batchId, pageIndex)
    }
    function loadBatch(id, index) {
        const page_ = app.call("getImportBatchRows", { batchId: String(id), offset: index * pageSize, limit: pageSize + 1 })
        batchId = String(id)
        pageIndex = index
        hasNextPage = page_.length > pageSize
        rows = page_.slice(0, pageSize)
    }
    function formatBytes(value) {
        const bytes = Number(value || 0)
        if (bytes < 1024)
            return `${bytes} B`
        if (bytes < 1024 * 1024)
            return `${(bytes / 1024).toFixed(1)} KiB`
        return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
    }
    function formatUtc(value) {
        const date = new Date(value)
        return isNaN(date.getTime()) ? String(value || "") : date.toLocaleString(Qt.locale("it_IT"), Locale.ShortFormat)
    }
    function startTask(method, startedMessage, ...args) {
        app.attempt(() => {
            const task = app.call(method, ...args)
            if (!task.cancelled)
                app.toast(startedMessage, false)
        })
    }
    function startImport() {
        startTask("startCsvImport", "Importazione CSV in corso", {
            accountId: importAccount.value,
            sourceName: sourceName.text,
            reviewMode: reviewMode.value
        })
    }
    function rowAction(method, payload, refreshLedger) {
        app.attempt(() => {
            const result = app.call(method, payload)
            if (refreshLedger)
                app.changed(result.stateSnapshot)
            else
                page.reload()
        }, "Riconciliazione aggiornata")
    }
    function saveRate() {
        app.attempt(() => {
            app.call("setFxRate", { currency: fxCurrency.value, date: fxDate.text, rate: fxRate.text })
            fxRate.clear()
            app.changed()
        }, "Tasso FX salvato")
    }

    Component.onCompleted: fxDate.text = app.today()
    Connections {
        target: page.app
        function onSessionReset() {
            page.defaultsPending = true
            page.batchId = ""
            page.pageIndex = 0
            page.rows = []
        }
        function onTaskFinished(result) {
            if (!result.ok)
                return
            page.app.attempt(() => {
                if (result.operation === "CSV_IMPORT") {
                    page.batchId = String(result.data.batchId)
                    page.pageIndex = 0
                    tabs.currentIndex = 1
                }
                if (page.active)
                    page.reload()
            })
        }
    }

    SectionTabs { id: tabs; objectName: "toolsTabs"; labels: ["Backup", "Riconciliazione", "Valute e cambi"] }

    StackLayout {
        Layout.fillWidth: true
        currentIndex: tabs.currentIndex

        RowLayout {
            spacing: Theme.gap
            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                spacing: Theme.gap
                Card {
                    title: "Backup"
                    Note { text: "I backup sono snapshot SQLite verificati. Creazione e verifica avvengono in background senza bloccare l'interfaccia. Vengono conservati gli ultimi 30 backup locali; i file esportati non vengono mai rimossi." }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        ActionButton { objectName: "backupCreate"; text: "Crea backup locale"; onClicked: page.startTask("startManagedBackup", "Creazione backup avviata") }
                        ActionButton { text: "Esporta backup…"; primary: false; onClicked: page.startTask("startExportBackup", "Esportazione backup avviata") }
                        ActionButton {
                            text: "Ripristina da file…"
                            primary: false
                            onClicked: page.app.confirm(
                                "Ripristinare un backup sostituirà lo stato corrente. Verrà creato automaticamente un backup di sicurezza. Continuare?",
                                () => page.startTask("startExternalRestore", "Verifica del backup avviata"))
                        }
                    }
                }
                Card {
                    warning: true
                    Label { text: "Ripristino sicuro"; color: Theme.accent; font.bold: true }
                    Note { text: "Prima di ogni ripristino viene creato automaticamente un backup dello stato corrente. Il file scelto viene verificato e, se necessario, migrato in staging prima di sostituire il database attivo. Durante il ripristino l'app entra in modalità manutenzione e non accetta modifiche." }
                }
            }
            Card {
                title: "Backup locali"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                BoundedList {
                    objectName: "backupList"
                    maxHeight: 520
                    emptyText: "Nessun backup locale."
                    model: page.backups
                    delegate: DataRow {
                        required property var modelData
                        title: modelData.name
                        subtitle: `${page.formatUtc(modelData.modifiedUtc)} · ${page.formatBytes(modelData.sizeBytes)} · schema v${modelData.schemaVersion}`
                        ActionButton {
                            text: "Ripristina"
                            primary: false
                            compact: true
                            onClicked: page.app.confirm(
                                `Ripristinare ${modelData.name}? Lo stato corrente verrà salvato automaticamente prima del ripristino.`,
                                () => page.startTask("startManagedRestore", "Verifica del backup avviata", modelData.name))
                        }
                    }
                }
            }
        }

        ColumnLayout {
            spacing: Theme.gap
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                Card {
                    title: "Importa CSV bancario"
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: 1
                    Note { text: "Le righe importate restano separate dal ledger finché non le confermi. Il file viene scelto con il dialogo di sistema (UTF-8 o Windows-1252, max 10 MB / 10.000 righe)." }
                    ChoiceField { id: importAccount; objectName: "importAccount"; label: "Conto" }
                    InputField { id: sourceName; objectName: "importSource"; label: "Fonte / banca"; placeholderText: "Nome banca" }
                    ChoiceField {
                        id: reviewMode
                        objectName: "importReviewMode"
                        label: "Modalità"
                        options: [
                            { value: "FULL_REVIEW", text: "Revisione completa" },
                            { value: "ASSISTED_REVIEW", text: "Revisione assistita" }
                        ]
                    }
                    ActionButton {
                        objectName: "importSubmit"
                        text: "Scegli CSV e importa…"
                        enabled: importAccount.value !== "" && !page.app.backend.busy
                        onClicked: page.startImport()
                    }
                }
                Card {
                    title: "Import recenti"
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: 1
                    BoundedList {
                        objectName: "importBatches"
                        maxHeight: 300
                        emptyText: "Nessun import."
                        model: page.batches
                        delegate: DataRow {
                            required property var modelData
                            title: modelData.source_name
                            subtitle: `${modelData.account_name} · ${modelData.review_mode} · ${modelData.row_count} righe`
                            valueColor: Theme.accent
                            value: String(modelData.id) === page.batchId ? "aperto" : ""
                            ActionButton {
                                text: "Apri"
                                primary: false
                                compact: true
                                onClicked: page.app.attempt(() => page.loadBatch(modelData.id, 0))
                            }
                        }
                    }
                }
            }
            Card {
                title: "Righe da riconciliare"
                Note { visible: page.batchId === ""; text: "Seleziona un import." }
                BoundedList {
                    objectName: "importRows"
                    visible: page.batchId !== ""
                    maxHeight: 640
                    emptyText: "Nessuna riga."
                    model: page.rows
                    delegate: ImportRow { app: page.app; tools: page }
                }
                RowLayout {
                    visible: page.batchId !== ""
                    ActionButton {
                        text: "Precedenti"
                        primary: false
                        compact: true
                        enabled: page.pageIndex > 0
                        onClicked: page.app.attempt(() => page.loadBatch(page.batchId, page.pageIndex - 1))
                    }
                    Label { text: `Pagina ${page.pageIndex + 1}`; color: Theme.secondary }
                    ActionButton {
                        text: "Successive"
                        primary: false
                        compact: true
                        enabled: page.hasNextPage
                        onClicked: page.app.attempt(() => page.loadBatch(page.batchId, page.pageIndex + 1))
                    }
                }
            }
        }

        RowLayout {
            spacing: Theme.gap
            Card {
                title: "Nuovo tasso FX storico"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                ChoiceField { id: fxCurrency; objectName: "fxCurrency"; label: "Valuta" }
                DateField { id: fxDate; objectName: "fxDate"; label: "Data" }
                InputField { id: fxRate; objectName: "fxRate"; label: "1 unità vale, in valuta base"; placeholderText: "0,92" }
                ActionButton { objectName: "fxSubmit"; text: "Salva tasso"; enabled: fxCurrency.value !== ""; onClicked: page.saveRate() }
            }
            Card {
                title: "Tassi salvati"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Note { text: "I tassi storici valorizzano conti e movimenti in valuta estera nella valuta base del book. Se manca un tasso, il reporting viene segnalato come incompleto invece di inventare un cambio." }
                BoundedList {
                    emptyText: "Nessun tasso salvato."
                    model: page.rates
                    delegate: DataRow {
                        required property var modelData
                        title: modelData.currency
                        detail: modelData.date
                        value: modelData.rate
                    }
                }
            }
        }
    }
}
