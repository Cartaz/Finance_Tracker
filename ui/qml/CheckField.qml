import QtQuick
import QtQuick.Controls

// Neumorphic switch used for boolean form options.
Switch {
    id: control
    implicitHeight: 44
    padding: 13
    opacity: enabled ? 1 : .42
    font.family: Theme.font
    font.pixelSize: 13
    activeFocusOnTab: true
    Accessible.name: text
    indicator: Item {
        width: 40
        height: 22
        x: control.width - width - 13
        y: (control.height - height) / 2
        InsetSurface {
            anchors.fill: parent
            radius: 11
            selected: control.checked || control.activeFocus
        }
        Rectangle {
            x: control.checked ? 21 : 5
            y: 4
            width: 14
            height: 14
            radius: 7
            color: control.checked ? Theme.accent : Theme.muted
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: Text {
        textFormat: Text.PlainText
        rightPadding: 56
        text: control.text
        color: Theme.primary
        font: control.font
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
    background: InsetSurface { radius: Theme.radiusMD }
}
