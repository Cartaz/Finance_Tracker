import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Accessible tab strip styled as neumorphic toggles; pair with a StackLayout.
TabBar {
    id: bar
    property var labels: []
    Layout.fillWidth: true
    spacing: 10
    background: Item {}
    Repeater {
        model: bar.labels
        TabButton {
            id: tab
            required property string modelData
            text: modelData
            width: implicitWidth
            implicitHeight: 32
            padding: 14
            font.family: Theme.font
            font.pixelSize: 13
            Accessible.name: modelData
            contentItem: Text {
                textFormat: Text.PlainText
                text: tab.text
                font: tab.font
                color: tab.checked ? Theme.accent : tab.hovered ? Theme.primary : Theme.secondary
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            background: Item {
                RaisedSurface {
                    anchors.fill: parent
                    radius: Theme.radiusMD
                    soft: true
                    visible: !tab.checked && !tab.visualFocus
                }
                InsetSurface {
                    anchors.fill: parent
                    radius: Theme.radiusMD
                    visible: tab.checked || tab.visualFocus
                    selected: tab.checked || tab.visualFocus
                }
            }
        }
    }
}
