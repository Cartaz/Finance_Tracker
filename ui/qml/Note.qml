import QtQuick
import QtQuick.Layouts

Text {
    textFormat: Text.PlainText
    color: Theme.muted
    font.family: Theme.font
    font.pixelSize: Theme.smallSize
    wrapMode: Text.WordWrap
    lineHeightMode: Text.FixedHeight
    lineHeight: font.pixelSize * 1.4
    Layout.fillWidth: true
}
