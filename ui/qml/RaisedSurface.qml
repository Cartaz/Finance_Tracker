import QtQuick
import QtQuick.Effects

// Raised neumorphic surface: dark lower-right and light upper-left shadows.
Item {
    id: root
    property real radius: Theme.radiusLG
    property bool soft: false
    property bool selected: false
    RectangularShadow {
        anchors.fill: body
        offset: Qt.vector2d(root.soft ? 5 : 9, root.soft ? 5 : 9)
        radius: body.radius
        blur: 1.2 * (root.soft ? 12 : 22)
        color: Qt.rgba(0, 0, 0, root.soft ? .66 : .78)
        cached: false
    }
    RectangularShadow {
        anchors.fill: body
        offset: Qt.vector2d(root.soft ? -4 : -7, root.soft ? -4 : -7)
        radius: body.radius
        blur: 1.2 * (root.soft ? 10 : 18)
        color: Qt.rgba(75 / 255, 75 / 255, 75 / 255, root.soft ? .12 : .15)
        cached: false
    }
    RectangularShadow {
        anchors.fill: body
        visible: root.selected
        radius: body.radius
        blur: 12
        color: Qt.rgba(1, .4, 0, .36)
        cached: false
    }
    Rectangle {
        id: body
        anchors.fill: parent
        color: Theme.surface
        radius: root.radius
        border.width: root.selected ? 1 : 0
        border.color: Theme.accent
    }
}
