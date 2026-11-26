import QtQuick
import QtQuick.Layouts

// Raised panel with an optional title; children stack vertically.
Item {
    id: card
    default property alias content: column.data
    property string title: ""
    property string kicker: ""
    property bool warning: false
    property alias spacing: column.spacing

    Layout.fillWidth: true
    implicitWidth: column.implicitWidth + 2 * Theme.padding
    implicitHeight: column.implicitHeight + 2 * Theme.padding

    RaisedSurface {
        anchors.fill: parent
        radius: Theme.radiusLG
        selected: card.warning
    }

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: Theme.padding
        spacing: 10

        Text {
            textFormat: Text.PlainText
            visible: card.kicker !== ""
            text: card.kicker
            color: Theme.accent
            font.family: Theme.font
            font.pixelSize: 10
            font.weight: Font.ExtraBold
            font.letterSpacing: 1.8
        }
        Text {
            textFormat: Text.PlainText
            visible: card.title !== ""
            text: card.title
            color: Theme.primary
            font.family: Theme.font
            font.pixelSize: 18
            font.bold: true
            Layout.fillWidth: true
            elide: Text.ElideRight
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }
    }
}
