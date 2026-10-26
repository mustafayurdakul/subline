import QtQuick

// A helper line: small and muted, wrapping when it is given a width.
Text {
    color: Theme.muted
    font.family: Theme.font
    font.pixelSize: Theme.sizeSmall
    wrapMode: Text.WordWrap
}
