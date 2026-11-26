import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: field
    property alias label: caption.text
    property alias text: input.text
    property alias placeholderText: input.placeholderText
    property alias validator: input.validator
    property alias input: input
    signal edited()
    signal accepted()

    function clear() { input.text = "" }

    Layout.fillWidth: true
    spacing: 6

    FieldLabel {
        id: caption
        visible: text !== ""
    }
    TextField {
        id: input
        Layout.fillWidth: true
        implicitHeight: 38
        padding: 10
        leftPadding: 12
        font.family: Theme.font
        font.pixelSize: Theme.bodySize
        color: readOnly ? Theme.muted : Theme.primary
        placeholderTextColor: Theme.muted
        selectionColor: Theme.accent
        selectedTextColor: Theme.surface
        selectByMouse: true
        activeFocusOnTab: true
        Accessible.name: caption.text
        onTextEdited: field.edited()
        onAccepted: field.accepted()
        background: InsetSurface {
            radius: Theme.radiusSM
            selected: input.activeFocus
        }
    }
}
