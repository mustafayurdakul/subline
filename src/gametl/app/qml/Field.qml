import QtQuick
import QtQuick.Controls.Basic as C

// A text field; the accent edge shows focus. With a `key` it shows that
// entry of the backend's settings and writes the edits back; without one it
// is a plain field (keys, names).
//
// `live: false` writes only when the typing is done (Enter, or leaving the
// field). Fields that restart a running overlay (game, source language,
// glossary, tone) use it: a pause mid-word must not restart the session
// with half a value.
C.TextField {
    id: root
    property bool secret: false
    property bool live: true
    property var map: backend.settings
    property string key: ""
    readonly property bool bound: key !== ""

    implicitWidth: 260
    implicitHeight: Theme.controlHeight
    leftPadding: 12
    rightPadding: 12
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.size
    opacity: enabled ? 1 : Theme.disabledOpacity
    echoMode: secret ? TextInput.Password : TextInput.Normal
    text: bound ? String(map[key] ?? "") : ""
    onTextEdited: if (bound && live) map[key] = text
    onEditingFinished: if (bound && !live && String(map[key] ?? "") !== text) map[key] = text

    background: Rectangle {
        radius: Theme.radius
        color: Theme.field
        border.color: root.activeFocus ? Theme.accent : root.hovered ? Theme.borderHover : Theme.borderStrong
        border.width: root.activeFocus ? 2 : 1
    }
}
