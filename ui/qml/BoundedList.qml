import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Height-bounded list with a visible scrollbar and an inset empty state.
ListView {
    id: list
    property string emptyText: "Nessun elemento."
    property int maxHeight: 420

    Layout.fillWidth: true
    Layout.preferredHeight: count === 0 ? empty.implicitHeight : Math.min(contentHeight, maxHeight)
    clip: true
    spacing: 0
    boundsBehavior: Flickable.StopAtBounds
    activeFocusOnTab: true
    Accessible.role: Accessible.List
    ScrollBar.vertical: ScrollBar {
        policy: list.contentHeight > list.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
        contentItem: Rectangle {
            implicitWidth: 4
            radius: 2
            color: Theme.accentLine
        }
    }

    EmptyState {
        id: empty
        visible: list.count === 0
        width: list.width
        text: list.emptyText
    }
}
