import QtQuick
import QtQuick.Controls.Basic

// A text field on a dark well; the accent border shows focus.
TextField {
    id: root
    property bool secret: false

    implicitWidth: 260
    implicitHeight: 34
    leftPadding: 12
    rightPadding: 12
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.size
    echoMode: secret ? TextInput.Password : TextInput.Normal

    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.field
        border.color: root.activeFocus ? Theme.accent : Theme.border
        border.width: 1
    }
}
