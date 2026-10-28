import QtQuick
import QtQuick.Controls.Basic

// A text field; the accent border shows focus. With a `key`
// it shows that entry of the backend's settings and writes every edit
// back; without one it is a plain field (keys, names).
TextField {
    id: root
    property bool secret: false
    property var map: backend.settings
    property string key: ""
    readonly property bool bound: key !== ""

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
        radius: Theme.radius
        color: Theme.field
        border.color: root.activeFocus ? Theme.accent : Theme.border
        border.width: 1
    }
}
