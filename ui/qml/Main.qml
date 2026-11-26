pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "pages"

ApplicationWindow {
    id: root
    required property var backend

    // Session state comes from Python; QML keeps only presentation state.
    property bool ready: false
    property var initial: null
    property var snapshot: null
    property var currencies: []
    property int revision: 0
    property int currentIndex: 0
    property string statusText: "Backend…"
    property string bootError: ""
    readonly property bool hasBook: initial !== null && !initial.needsSetup && snapshot !== null
    readonly property string baseCurrency: snapshot && snapshot.book ? snapshot.book.currency : ""
    readonly property var views: [
        { key: "dashboard", label: "Dashboard" },
        { key: "transactions", label: "Transazioni" },
        { key: "accounts", label: "Conti" },
        { key: "budgets", label: "Budget" },
        { key: "forecast", label: "Forecast" },
        { key: "loans", label: "Prestiti" },
        { key: "scheduled", label: "Programmate" },
        { key: "tools", label: "Strumenti" }
    ]
    readonly property var kindLabels: ({
        EXPENSE: "Spesa", INCOME: "Entrata", TRANSFER: "Giroconto", REFUND: "Rimborso",
        OPENING_BALANCE: "Saldo iniziale", ADJUSTMENT: "Rettifica", REVERSAL: "Storno"
    })
    readonly property var accountTypeLabels: ({ ASSET: "Conto", LIABILITY: "Debito", EXPENSE: "Spesa", INCOME: "Entrata" })

    signal sessionReset()
    signal taskFinished(var result)

    visible: true
    width: 1440
    height: 900
    minimumWidth: 1200
    minimumHeight: 800
    title: "Finance Tracker"
    color: Theme.surface
    font.family: Theme.font
    font.pixelSize: Theme.bodySize

    palette.window: Theme.surface
    palette.windowText: Theme.primary
    palette.base: Theme.surface
    palette.alternateBase: Theme.surface
    palette.text: Theme.primary
    palette.button: Theme.surface
    palette.buttonText: Theme.secondary
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.surface
    palette.placeholderText: Theme.muted

    // ---- backend access -------------------------------------------------
    function call(method, ...args) {
        const result = root.backend[method](...args)
        if (!result || !result.ok)
            throw new Error(result && result.error ? result.error.message : "Operazione fallita")
        return result.data
    }
    // Run a UI action, reporting failures as an error toast.
    function attempt(action, successMessage) {
        try {
            action()
            if (successMessage)
                toast(successMessage, false)
            return true
        } catch (error) {
            toast(error.message, true)
            return false
        }
    }
    function toast(message, bad) {
        toastLabel.text = message
        toastBox.bad = !!bad
        toastBox.visible = true
        toastTimer.restart()
    }
    function confirm(message, onAccepted) {
        confirmDialog.message = message
        confirmDialog.confirmAction = onAccepted
        confirmDialog.open()
    }
    // Publish a fresh canonical snapshot and let visible pages reload.
    function changed(newSnapshot) {
        snapshot = newSnapshot ? newSnapshot : call("getSnapshot")
        revision += 1
    }
    function boot() {
        ready = false
        bootError = ""
        const state = call("getInitialState")
        currencies = state.currencies
        initial = state
        snapshot = state.needsSetup ? null : call("getSnapshot")
        statusText = "Backend connesso"
        ready = true
        revision += 1
    }
    function completeSetup(newSnapshot) {
        initial = call("getInitialState")
        snapshot = newSnapshot
        currentIndex = 0
        revision += 1
    }

    // ---- presentation helpers (no financial arithmetic) -----------------
    function money(minor, currency) {
        return root.backend.formatMoney(minor === undefined || minor === null ? "" : String(minor), currency || "")
    }
    function bps(value) {
        return root.backend.formatPercentBps(value === undefined || value === null ? "" : String(value))
    }
    function pad(value) { return String(value).padStart(2, "0") }
    function isoDate(date) { return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` }
    function today() { return isoDate(new Date()) }
    function monthStart() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01` }
    function currentMonth() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}` }
    // Calendar month arithmetic clamped to the target month's last day.
    function addMonths(isoText, months) {
        const base = new Date(isoText + "T00:00:00")
        const day = base.getDate()
        const target = new Date(base.getFullYear(), base.getMonth() + months, 1)
        const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate()
        target.setDate(Math.min(day, lastDay))
        return isoDate(target)
    }
    function monthsFromToday(months) { return addMonths(today(), months) }

    function accounts() { return snapshot ? snapshot.accounts : [] }
    function accountById(id) { return accounts().find(item => String(item.id) === String(id)) }
    function balanceAccounts(postableOnly) {
        return accounts().filter(item => (item.type === "ASSET" || item.type === "LIABILITY")
            && (!postableOnly || (!item.placeholder && !item.archived)))
    }
    function categoryPath(account) {
        const names = []
        const seen = {}
        let current = account
        while (current) {
            if (seen[current.id])
                return names.reverse().join(" › ") + " › ?"
            seen[current.id] = true
            names.push(current.name)
            current = current.parentId === null || current.parentId === undefined ? null : accountById(current.parentId)
        }
        return names.reverse().join(" › ")
    }
    function accountLabel(account) {
        if (account.type === "EXPENSE" || account.type === "INCOME")
            return categoryPath(account)
        return account.currency ? `${account.name} · ${account.currency}` : account.name
    }
    function accountOptions(items) {
        return items.map(item => ({ value: String(item.id), text: accountLabel(item) }))
    }
    // Counterparties come from backend-owned posting capabilities.
    function counterOptions(sourceId, kind) {
        const source = accountById(sourceId)
        if (!source || !source.postingCapabilities || !source.postingCapabilities[kind])
            return []
        const allowed = source.postingCapabilities[kind].map(String)
        return accountOptions(accounts().filter(item => allowed.indexOf(String(item.id)) >= 0))
    }
    function idOptions(ids) {
        const allowed = (ids || []).map(String)
        return accountOptions(accounts().filter(item => allowed.indexOf(String(item.id)) >= 0))
    }
    function currencyOptions(excludeBase) {
        return currencies.filter(item => !excludeBase || item.code !== baseCurrency)
            .map(item => ({ value: item.code, text: item.code }))
    }
    function transactionFlow(t) {
        const sources = t.sourceAccountNames || []
        const destinations = t.destinationAccountNames || []
        if (sources.length && destinations.length)
            return `${sources.join(", ")} → ${destinations.join(", ")}`
        if (sources.length)
            return `Da ${sources.join(", ")}`
        if (destinations.length)
            return `A ${destinations.join(", ")}`
        return "—"
    }
    function transactionAmount(t) {
        if (t.amountMinor === null || t.amountMinor === undefined)
            return "—"
        const formatted = money(t.amountMinor, t.currency_code)
        const hasSource = (t.sourceAccountNames || []).length > 0
        const hasDestination = (t.destinationAccountNames || []).length > 0
        if (hasSource && !hasDestination)
            return "−" + formatted
        if (!hasSource && hasDestination)
            return "+" + formatted
        return formatted
    }
    function missingFxText(items) {
        return (items || []).map(item => `${item.currency} · ${item.date}`).join(" · ")
    }

    function start() {
        try {
            boot()
        } catch (error) {
            bootError = error.message
        }
    }

    // Pages initialise their default dates in their own onCompleted handlers;
    // booting afterwards guarantees the first reload sees those values.
    Component.onCompleted: Qt.callLater(start)

    onClosing: function(close) {
        if (root.backend.busy) {
            close.accepted = false
            toast("Attendi il completamento dell'importazione, del backup o del ripristino prima di chiudere Finance Tracker.", true)
        }
    }

    Connections {
        target: root.backend
        function onBackupTaskFinished(result) {
            if (!result.ok) {
                root.toast(result.error ? result.error.message : "Operazione fallita", true)
            } else if (result.requiresReload) {
                const safety = result.data && result.data.safetyBackup ? ` Backup di sicurezza: ${result.data.safetyBackup}.` : ""
                root.sessionReset()
                root.start()
                if (root.ready)
                    root.toast(`Ripristino completato.${safety}`, false)
                return
            } else if (result.operation === "CSV_IMPORT") {
                root.toast(`Importate ${result.data.rowCount} righe`, false)
            } else if (result.operation === "BACKUP_CREATE") {
                root.toast("Backup locale creato", false)
            } else if (result.operation === "BACKUP_EXPORT") {
                root.toast("Backup esportato", false)
            }
            root.taskFinished(result)
        }
    }

    Card {
        objectName: "bootError"
        visible: root.bootError !== ""
        anchors.centerIn: parent
        width: 520
        kicker: "ERRORE"
        title: "Impossibile caricare i dati"
        Note { text: root.bootError }
        Note { text: "I dettagli sono nel file di log. Puoi riprovare senza chiudere l'applicazione." }
        ActionButton {
            objectName: "bootRetry"
            text: "Riprova"
            onClicked: root.start()
        }
    }

    SetupPage {
        anchors.fill: parent
        app: root
        visible: root.ready && !root.hasBook && root.initial !== null
    }

    Item {
        anchors.fill: parent
        anchors.margins: 18
        visible: root.ready && root.hasBook

        Item {
            id: sidebar
            objectName: "sidebar"
            width: Theme.sidebarWidth
            height: parent.height
            RaisedSurface {
                anchors.fill: parent
                radius: Theme.radiusXL
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                anchors.topMargin: 18
                anchors.bottomMargin: 18
                spacing: 20
                Column {
                    Layout.fillWidth: true
                    Layout.leftMargin: 6
                    spacing: 2
                    Text {
                        textFormat: Text.PlainText
                        text: "Finance Tracker"
                        color: Theme.primary
                        font.family: Theme.font
                        font.pixelSize: 15
                        font.bold: true
                    }
                    Text {
                        textFormat: Text.PlainText
                        text: root.snapshot && root.snapshot.book ? root.snapshot.book.name : ""
                        color: Theme.muted
                        font.family: Theme.font
                        font.pixelSize: Theme.smallSize
                        elide: Text.ElideRight
                        width: parent.width
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 9
                    Repeater {
                        model: root.views
                        ActionButton {
                            required property var modelData
                            required property int index
                            objectName: "nav-" + modelData.key
                            text: modelData.label
                            primary: false
                            alignLeft: true
                            selected: root.currentIndex === index
                            Layout.fillWidth: true
                            onClicked: root.currentIndex = index
                        }
                    }
                }
                Item { Layout.fillHeight: true }
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 56
                    InsetSurface { anchors.fill: parent }
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 9
                        Rectangle {
                            implicitWidth: 9
                            implicitHeight: 9
                            radius: 4.5
                            color: root.backend.busy ? Theme.accent : Theme.muted
                        }
                        Column {
                            spacing: 2
                            Note { text: root.backend.busy ? "Operazione in corso" : "Backend" }
                            Text {
                                objectName: "bridgeStatus"
                                textFormat: Text.PlainText
                                text: root.statusText
                                color: Theme.primary
                                font.family: Theme.font
                                font.pixelSize: Theme.smallSize
                                font.bold: true
                            }
                        }
                    }
                }
            }
        }

        ColumnLayout {
            anchors.left: sidebar.right
            anchors.leftMargin: 24
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Layout.rightMargin: 6
                ColumnLayout {
                    spacing: 4
                    Text {
                        textFormat: Text.PlainText
                        text: root.views[root.currentIndex].label.toUpperCase()
                        color: Theme.accent
                        font.family: Theme.font
                        font.pixelSize: 11
                        font.weight: Font.ExtraBold
                        font.letterSpacing: 1.98
                        Accessible.role: Accessible.Heading
                        Accessible.name: text
                    }
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    objectName: "refreshButton"
                    text: "Aggiorna"
                    primary: false
                    compact: true
                    onClicked: root.attempt(() => root.changed())
                }
            }

            Item {
                objectName: "maintenanceBanner"
                visible: root.backend.maintenance
                Layout.fillWidth: true
                implicitHeight: 42
                InsetSurface { anchors.fill: parent; selected: true }
                Text {
                    textFormat: Text.PlainText
                    anchors.centerIn: parent
                    text: "Operazione sui dati in corso… le modifiche sono temporaneamente bloccate."
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: Theme.smallSize
                    font.bold: true
                    Accessible.role: Accessible.AlertMessage
                    Accessible.name: text
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: root.currentIndex
                DashboardPage { objectName: "dashboardPage"; app: root }
                TransactionsPage { objectName: "transactionsPage"; app: root }
                AccountsPage { objectName: "accountsPage"; app: root }
                BudgetsPage { objectName: "budgetsPage"; app: root }
                ForecastPage { objectName: "forecastPage"; app: root }
                LoansPage { objectName: "loansPage"; app: root }
                ScheduledPage { objectName: "scheduledPage"; app: root }
                ToolsPage { objectName: "toolsPage"; app: root }
            }
        }
    }

    Item {
        id: toastBox
        property bool bad: false
        objectName: "toast"
        visible: false
        z: 100
        x: root.width - width - 28
        y: 24
        width: Math.min(460, root.width - 48)
        height: toastLabel.implicitHeight + 28
        RaisedSurface {
            anchors.fill: parent
            radius: Theme.radiusMD
            soft: true
            selected: !toastBox.bad
        }
        Rectangle {
            x: 12
            y: 12
            width: 4
            height: parent.height - 24
            radius: 2
            color: toastBox.bad ? Theme.danger : Theme.accent
        }
        Text {
            id: toastLabel
            objectName: "toastText"
            textFormat: Text.PlainText
            x: 28
            width: parent.width - 44
            anchors.verticalCenter: parent.verticalCenter
            color: toastBox.bad ? Theme.danger : Theme.primary
            font.family: Theme.font
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Accessible.role: Accessible.AlertMessage
            Accessible.name: text
        }
        Timer {
            id: toastTimer
            interval: 3600
            onTriggered: toastBox.visible = false
        }
    }

    Dialog {
        id: confirmDialog
        property string message: ""
        property var confirmAction: null
        objectName: "confirmDialog"
        anchors.centerIn: parent
        modal: true
        title: "Conferma"
        standardButtons: Dialog.Ok | Dialog.Cancel
        width: 480
        padding: 22
        background: RaisedSurface { radius: Theme.radiusLG }
        header: Text {
            textFormat: Text.PlainText
            text: confirmDialog.title
            color: Theme.primary
            font.family: Theme.font
            font.pixelSize: 18
            font.bold: true
            padding: 22
            bottomPadding: 0
        }
        Text {
            textFormat: Text.PlainText
            text: confirmDialog.message
            wrapMode: Text.WordWrap
            width: parent.width
            color: Theme.secondary
            font.family: Theme.font
            font.pixelSize: Theme.bodySize
        }
        onAccepted: {
            const action = confirmAction
            confirmAction = null
            if (action)
                action()
        }
        onRejected: confirmAction = null
    }
}
