pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

// Payee autocomplete backed by the payee service: suggest, pick or create.
ColumnLayout {
    id: field
    required property var app
    property alias label: input.label
    property alias inputName: input.objectName
    property string payeeId: ""
    property var suggestions: []

    function clear() {
        payeeId = ""
        suggestions = []
        input.clear()
        panel.visible = false
    }
    function suggest(query) {
        payeeId = ""
        suggestions = query.trim() === "" ? [] : app.call("suggestPayees", query)
        panel.visible = query.trim() !== ""
    }
    function choose(id, name) {
        payeeId = String(id)
        input.text = name
        panel.visible = false
    }
    // Payload fields for a posting: a picked payee by id, otherwise the typed
    // name, which the backend resolves or creates in the same transaction.
    function payloadFields() {
        if (payeeId !== "")
            return { payeeId: payeeId }
        const text = input.text.trim()
        return text === "" ? {} : { payeeName: text }
    }
    function create() {
        const item = app.call("createPayee", input.text)
        choose(item.id, item.name)
    }

    Layout.fillWidth: true
    spacing: 10

    InputField {
        id: input
        label: "Merchant"
        placeholderText: "Inizia a scrivere…"
        onEdited: field.app.attempt(() => field.suggest(input.text))
    }
    Item {
        id: panel
        visible: false
        Layout.fillWidth: true
        implicitHeight: column.implicitHeight + 20
        InsetSurface { anchors.fill: parent; radius: Theme.radiusSM }
        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
            Repeater {
                model: field.suggestions
                ActionButton {
                    required property var modelData
                    primary: false
                    compact: true
                    Layout.fillWidth: true
                    text: `${modelData.name}  ·  ${modelData.usageCount}×`
                    onClicked: field.choose(modelData.id, modelData.name)
                }
            }
            ActionButton {
                primary: false
                compact: true
                Layout.fillWidth: true
                text: `+ Usa “${input.text}”`
                onClicked: field.app.attempt(() => field.create())
            }
        }
    }
}
