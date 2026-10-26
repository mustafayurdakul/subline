import QtQuick
import QtQuick.Controls.Basic

// A multi-line field bound to `map[key]`, one entry per line (ignore
// patterns, zones).
Rectangle {
    id: root
    property string placeholderText: ""
    property var map: backend.settings
    property string key: ""

    implicitWidth: 300
    implicitHeight: 84
    radius: Theme.radius
    color: Theme.field
    border.color: area.activeFocus ? Theme.accent : Theme.border

    ScrollView {
        anchors.fill: parent
        anchors.margins: 1
        clip: true
        TextArea {
            id: area
            placeholderText: root.placeholderText
            placeholderTextColor: Theme.muted
            color: Theme.text
            selectionColor: Theme.selection
            selectedTextColor: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.size
            wrapMode: TextEdit.NoWrap
            leftPadding: 11
            rightPadding: 11
            topPadding: 7
            background: null
            Binding on text { value: String(root.map[root.key] ?? "") }
            onTextChanged: if (activeFocus) root.map[root.key] = text  // the user's edits, not the binding's
        }
    }
}
