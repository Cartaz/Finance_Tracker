import QtQuick
import QtQuick.Effects

// Pressed-in neumorphic surface drawn by a small signed-distance shader.
Item {
    id: root
    property real radius: Theme.radiusMD
    property bool strong: false
    property bool selected: false
    RectangularShadow {
        anchors.fill: parent
        visible: root.selected
        radius: root.radius
        blur: 8
        color: Qt.rgba(1, .4, 0, .36)
        cached: false
    }
    RectangularShadow {
        anchors.fill: parent
        visible: root.selected
        radius: root.radius
        blur: 17
        color: Qt.rgba(1, .4, 0, .16)
        cached: false
    }
    Rectangle {
        anchors.fill: parent
        color: Theme.surface
        radius: root.radius
    }
    ShaderEffect {
        anchors.fill: parent
        property vector2d size: Qt.vector2d(width, height)
        property real cornerRadius: root.radius
        property real depth: root.strong ? 5 : 3
        fragmentShader: Qt.resolvedUrl("shaders/inset.frag.qsb")
    }
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        radius: root.radius
        border.width: root.selected ? 1 : 0
        border.color: Theme.accent
    }
}
