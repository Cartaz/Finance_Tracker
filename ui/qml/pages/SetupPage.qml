pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: page
    required property var app

    function submit() {
        page.app.attempt(() => {
            const state = page.app.call("setup", {
                userName: userName.text,
                bookName: bookName.text,
                currency: currency.value
            })
            page.app.completeSetup(state)
        }, "Book creato")
    }

    onVisibleChanged: {
        if (visible && page.app.initial) {
            currency.setOptions(page.app.currencyOptions(false))
            currency.select(page.app.initial.bookCurrency)
        }
    }

    Card {
        anchors.centerIn: parent
        width: 460
        kicker: "PRIMO AVVIO"
        title: "Configura il tuo book"
        InputField { id: userName; objectName: "setupUserName"; label: "Nome"; placeholderText: "Il tuo nome" }
        InputField { id: bookName; objectName: "setupBookName"; label: "Book"; text: "Personale" }
        ChoiceField { id: currency; objectName: "setupCurrency"; label: "Valuta base" }
        ActionButton {
            objectName: "setupSubmit"
            text: "Crea book"
            Layout.fillWidth: true
            onClicked: page.submit()
        }
    }
}
