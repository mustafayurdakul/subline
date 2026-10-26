import QtQuick

// Body text in the app's font and colour; pages set a size or colour only when it differs.
Text {
    color: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.size
}
