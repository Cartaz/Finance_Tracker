import QtQuick
import QtQuick.Layouts

// One list line: title/subtitle on the left, detail and value on the right,
// optional action buttons underneath.
Item {
    id: row
    property string title: ""
    property string subtitle: ""
    property string detail: ""
    property string value: ""
    property color valueColor: Theme.primary
    default property alias actions: actionRow.data

    width: ListView.view ? ListView.view.width - 12 : parent ? parent.width : implicitWidth
    implicitWidth: layout.implicitWidth
    implicitHeight: layout.implicitHeight + 18

    ColumnLayout {
        id: layout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Text {
                    textFormat: Text.PlainText
                    text: row.title
                    color: Theme.primary
                    font.family: Theme.font
                    font.pixelSize: Theme.bodySize
                    font.bold: true
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    textFormat: Text.PlainText
                    visible: row.subtitle !== ""
                    text: row.subtitle
                    color: Theme.secondary
                    font.family: Theme.font
                    font.pixelSize: Theme.smallSize
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
            Text {
                textFormat: Text.PlainText
                visible: row.detail !== ""
                text: row.detail
                color: Theme.muted
                font.family: Theme.font
                font.pixelSize: Theme.smallSize
                horizontalAlignment: Text.AlignRight
                Layout.maximumWidth: 320
                elide: Text.ElideLeft
            }
            Text {
                textFormat: Text.PlainText
                visible: row.value !== ""
                text: row.value
                color: row.valueColor
                font.family: Theme.font
                font.pixelSize: Theme.bodySize
                font.bold: true
                horizontalAlignment: Text.AlignRight
            }
        }
        Flow {
            id: actionRow
            Layout.fillWidth: true
            spacing: 10
            visible: children.length > 0
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.line
    }
}
