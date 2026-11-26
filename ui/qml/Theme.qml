pragma Singleton
import QtQuick

// Neumorphic design tokens shared with the author's other Qt Quick apps:
// a single rgb(20,20,20) surface, depth from shadows, rgb(255,102,0) accent.
QtObject {
    readonly property color surface: "#141414"
    readonly property color accent: "#ff6600"
    readonly property color primary: "#e1e1e1"
    readonly property color secondary: "#878787"
    readonly property color muted: "#5a5a5a"
    readonly property color danger: "#ff6b6b"
    readonly property color line: Qt.rgba(1, 1, 1, 0.05)
    readonly property color accentLine: Qt.rgba(1, 0.4, 0, 0.35)
    readonly property string font: "DejaVu Sans"
    readonly property int radiusXL: 28
    readonly property int radiusLG: 22
    readonly property int radiusMD: 16
    readonly property int radiusSM: 12
    readonly property int gap: 22
    readonly property int padding: 18
    readonly property int sidebarWidth: 210
    readonly property int bodySize: 14
    readonly property int smallSize: 12
    readonly property int titleSize: 22
}
