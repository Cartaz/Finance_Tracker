import QtQuick

InputField {
    placeholderText: "HH:MM (opzionale)"
    validator: RegularExpressionValidator { regularExpression: /^\d{0,2}(:\d{0,2}(:\d{0,2})?)?$/ }
}
