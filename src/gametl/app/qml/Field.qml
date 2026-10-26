import QtQuick
import QtQuick.Controls.Basic

// A text field on a dark well; the accent border shows focus. With `map`
// and `key` it shows that entry of the backend's settings and writes every
// edit back; without them it is a plain field.
TextField {
    id: root
    property bool secret: false
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""

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
    text: bound ? String(map[key] ?? "") : ""
    onTextEdited: if (bound) map[key] = text

    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.field
        border.color: root.activeFocus ? Theme.accent : Theme.border
        border.width: 1
    }
}
