pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Neumorphic ComboBox over [{value, text}] options. Values are strings so
// identifiers cross back to Python unchanged.
ColumnLayout {
    id: field
    property alias label: caption.text
    property var options: []
    property alias combo: combo
    readonly property string value: combo.currentIndex >= 0 && combo.currentIndex < options.length
        ? String(options[combo.currentIndex].value) : ""
    readonly property string currentText: combo.currentIndex >= 0 && combo.currentIndex < options.length
        ? String(options[combo.currentIndex].text) : ""
    signal activated()

    function indexOfValue(target) {
        for (let i = 0; i < options.length; ++i) {
            if (String(options[i].value) === String(target))
                return i
        }
        return -1
    }
    function select(target) {
        const index = indexOfValue(target)
        if (index >= 0)
            combo.currentIndex = index
        return index >= 0
    }
    // Replace options while keeping the current selection when still valid.
    function setOptions(next) {
        const previous = value
        options = next || []
        const index = indexOfValue(previous)
        combo.currentIndex = index >= 0 ? index : (options.length ? 0 : -1)
    }

    Layout.fillWidth: true
    spacing: 6

    FieldLabel {
        id: caption
        visible: text !== ""
    }
    ComboBox {
        id: combo
        Layout.fillWidth: true
        implicitHeight: 38
        padding: 10
        rightPadding: 30
        model: field.options
        textRole: "text"
        font.family: Theme.font
        font.pixelSize: Theme.bodySize
        activeFocusOnTab: true
        opacity: enabled ? 1 : .42
        Accessible.name: caption.text
        onActivated: field.activated()
        contentItem: Text {
            textFormat: Text.PlainText
            leftPadding: 2
            text: field.currentText
            font: combo.font
            color: Theme.primary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            textFormat: Text.PlainText
            x: combo.width - 22
            y: (combo.height - height) / 2
            text: "⌄"
            color: Theme.secondary
        }
        background: InsetSurface {
            radius: Theme.radiusSM
            selected: combo.activeFocus || combo.popup.visible
        }
        delegate: ItemDelegate {
            id: choice
            required property var modelData
            required property int index
            width: combo.width
            highlighted: combo.highlightedIndex === index
            contentItem: Text {
                textFormat: Text.PlainText
                text: choice.modelData.text
                font: combo.font
                color: choice.highlighted ? Theme.accent : Theme.primary
                elide: Text.ElideRight
            }
            background: Rectangle {
                color: Theme.surface
                radius: 8
                border.color: Theme.accentLine
                border.width: choice.highlighted ? 1 : 0
            }
        }
        popup: Popup {
            y: combo.height + 4
            width: combo.width
            padding: 6
            height: Math.min(300, contentItem.implicitHeight + 12)
            background: Rectangle {
                color: Theme.surface
                radius: Theme.radiusSM
                border.color: Theme.muted
            }
            contentItem: ListView {
                implicitHeight: contentHeight
                model: combo.popup.visible ? combo.delegateModel : null
                clip: true
                ScrollIndicator.vertical: ScrollIndicator {}
            }
        }
    }
}
