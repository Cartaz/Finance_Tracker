import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Scrollable page body. Pages reload when shown and after data revisions.
ScrollView {
    id: page
    default property alias content: column.data
    required property var app
    readonly property bool active: visible && app.ready && app.hasBook

    function reload() {}

    // Margin keeps neumorphic shadows inside the clipped scroll viewport.
    readonly property int shadowMargin: 16
    contentWidth: availableWidth
    contentHeight: column.implicitHeight + 2 * shadowMargin
    clip: true

    onActiveChanged: if (active) app.attempt(() => page.reload())
    Connections {
        target: page.app
        function onRevisionChanged() {
            if (page.active)
                page.app.attempt(() => page.reload())
        }
    }

    ColumnLayout {
        id: column
        x: page.shadowMargin
        y: page.shadowMargin
        width: page.availableWidth - 2 * page.shadowMargin - 8
        spacing: Theme.gap
    }
}
