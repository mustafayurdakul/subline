import QtQuick

// Press-to-set: click, press the keys, done. Esc leaves the field as it
// was, Backspace restores `fallback`. While it records, the backend lets go
// of the global hotkeys, or the combination in use would never arrive.
Rectangle {
    id: root
    property var map: null
    property string key: ""
    property string fallback: ""
    readonly property string combo: map !== null && key !== "" ? String(map[key] ?? "") : ""

    implicitWidth: 200
    implicitHeight: 34
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: activeFocus ? Theme.accent : Theme.border
    activeFocusOnTab: true

    function pretty(text) {
        return text.split("+").map(function(part) {
            return part.length ? part.charAt(0).toUpperCase() + part.slice(1) : part
        }).join(" + ")
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: root.activeFocus ? "press the keys" : root.pretty(root.combo)
        color: root.activeFocus ? Theme.muted : Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.size
    }
    Text {
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        visible: root.activeFocus
        text: "Esc"
        color: Theme.muted
        font.family: Theme.font
        font.pixelSize: Theme.sizeSmall
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.forceActiveFocus()
    }

    onActiveFocusChanged: backend.setHotkeyCapture(activeFocus)
    Keys.onPressed: function(event) {
        event.accepted = true
        if (event.key === Qt.Key_Escape) {
            root.focus = false
            return
        }
        if (event.key === Qt.Key_Backspace && event.modifiers === Qt.NoModifier) {
            map[key] = root.fallback
            root.focus = false
            return
        }
        var combo = backend.comboFromKey(event.key, event.modifiers)
        if (combo !== "") {
            map[key] = combo
            root.focus = false
        }
    }
}
