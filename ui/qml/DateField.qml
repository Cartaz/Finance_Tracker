import QtQuick

// ISO calendar date entry; the backend validates and canonicalizes the value.
InputField {
    id: dateField
    property bool monthOnly: false
    placeholderText: dateField.monthOnly ? "AAAA-MM" : "AAAA-MM-GG"
    validator: RegularExpressionValidator {
        regularExpression: dateField.monthOnly ? /^\d{0,4}(-\d{0,2})?$/ : /^\d{0,4}(-\d{0,2}(-\d{0,2})?)?$/
    }
}
