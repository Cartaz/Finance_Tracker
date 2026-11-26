import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string text: ""
    Layout.fillWidth: true
    implicitHeight: 46
    InsetSurface { anchors.fill: parent }
    Text {
        textFormat: Text.PlainText
        anchors.fill: parent
        anchors.margins: 14
        text: root.text
        color: Theme.muted
        font.family: Theme.font
        font.pixelSize: Theme.bodySize
        wrapMode: Text.WordWrap
        verticalAlignment: Text.AlignVCenter
    }
}
