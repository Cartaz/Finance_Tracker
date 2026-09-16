import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml

ApplicationWindow {
    id: root
    required property QtObject backend

    visible: true
    width: 960
    height: 640
    minimumWidth: 720
    minimumHeight: 520
    title: "Finance Tracker · anteprima Qt Quick"
    color: theme.surface

    Theme { id: theme }

    onClosing: function(close) {
        if (backend.busy) {
            close.accepted = false
            backend.explainBusy()
        }
    }

    Connections {
        target: backend
        function onErrorOccurred(message) {
            feedback.text = message
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 36
        spacing: 24

        Label {
            text: "FINANCE TRACKER · PROTOTIPO QML"
            color: theme.accent
            font.family: "Noto Sans"
            font.pixelSize: 13
            font.bold: true
        }
        Label {
            objectName: "bookNameValue"
            text: backend.bookName
            color: theme.textPrimary
            font.family: "Noto Sans"
            font.pixelSize: 29
            font.bold: true
            Layout.fillWidth: true
        }
        Rectangle {
            color: theme.surface
            border.color: "#303030"
            border.width: 1
            radius: theme.cornerRadius
            Layout.fillWidth: true
            Layout.preferredHeight: 190

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 28
                spacing: 10
                Label {
                    text: "Patrimonio netto · unità minori (dato grezzo esatto)"
                    color: theme.textSecondary
                    font.family: "Noto Sans"
                    font.pixelSize: 15
                }
                Label {
                    objectName: "netWorthValue"
                    text: backend.netWorthMinor
                    color: theme.textPrimary
                    font.family: "Noto Sans"
                    font.pixelSize: 32
                    font.bold: true
                    Accessible.name: "Patrimonio netto in unità minori"
                }
                Label {
                    text: backend.currency
                    color: theme.accent
                    font.family: "Noto Sans"
                    font.pixelSize: 15
                }
            }
        }
        Label {
            text: "Questa anteprima è di sola lettura. L'interfaccia attuale resta il punto di accesso completo alle operazioni."
            color: theme.textSecondary
            font.family: "Noto Sans"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Button {
            text: "Aggiorna dal database"
            activeFocusOnTab: true
            onClicked: root.backend.refresh()
        }
        Label {
            id: feedback
            objectName: "previewFeedback"
            text: ""
            color: theme.accent
            font.family: "Noto Sans"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            Accessible.role: Accessible.AlertMessage
        }
        Item { Layout.fillHeight: true }
    }
}
