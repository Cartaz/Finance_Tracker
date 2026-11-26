import QtQuick
import QtQuick.Layouts

Card {
    id: metric
    property string label: ""
    property string value: ""
    Layout.preferredWidth: 1
    FieldLabel { text: metric.label; elide: Text.ElideRight; wrapMode: Text.NoWrap }
    Text {
        textFormat: Text.PlainText
        text: metric.value
        color: Theme.primary
        font.family: Theme.font
        font.pixelSize: 20
        font.bold: true
        Layout.fillWidth: true
        elide: Text.ElideRight
    }
}
