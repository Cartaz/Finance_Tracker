import QtQuick
import QtQuick.Controls

// Neumorphic button. A primary action reads as an orange inset state, never
// as an opaque fill; secondary actions stay raised with grey text.
Button {
    id: control
    property bool primary: true
    property bool compact: false
    property bool selected: false
    property bool alignLeft: false
    readonly property bool accented: (primary || selected) && enabled
    implicitHeight: compact ? 30 : 36
    padding: compact ? 10 : 14
    horizontalPadding: padding
    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    font.family: Theme.font
    font.pixelSize: compact ? 13 : 14
    opacity: enabled ? 1 : .42
    activeFocusOnTab: true
    Accessible.name: text
    contentItem: Text {
        id: label
        textFormat: Text.PlainText
        text: control.text
        font: control.font
        color: control.accented ? Theme.accent : control.hovered ? Theme.primary : Theme.secondary
        horizontalAlignment: control.alignLeft ? Text.AlignLeft : Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Item {
        RaisedSurface {
            anchors.fill: parent
            radius: Theme.radiusMD
            soft: true
            visible: !control.down && !control.accented && !control.activeFocus
        }
        InsetSurface {
            anchors.fill: parent
            radius: Theme.radiusMD
            visible: control.down || control.accented || control.activeFocus
            selected: control.accented || control.activeFocus
        }
    }
}
