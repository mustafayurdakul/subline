import QtQuick
import QtQuick.Controls.Basic

// A multi-line field, one entry per line (ignore patterns, zones). With
// `map` and `key` it follows and writes that settings entry.
Rectangle {
    id: root
    property string placeholderText: ""
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""

    implicitWidth: 300
    implicitHeight: 84
    radius: Theme.radiusSmall
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
            Binding on text { when: root.bound; value: root.bound ? String(root.map[root.key] ?? "") : "" }
            onTextChanged: if (activeFocus && root.bound) root.map[root.key] = text
        }
    }
}
