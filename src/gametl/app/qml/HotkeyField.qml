import QtQuick
import "Format.js" as Format

// Press-to-set, bound to `map[key]`: click, press the keys, done. Esc
// leaves the field as it was, Backspace restores `fallback`, Tab moves on.
// While it records, the backend lets go of the global hotkeys, or the
// combination in use would never arrive.
Rectangle {
    id: root
    property var map: backend.settings
    property string key: ""
    property string fallback: ""
    readonly property string combo: String(map[key] ?? "")
    readonly property bool capturing: activeFocus
    property string refusal: ""  // why the last press was not taken, shown while recording

    implicitWidth: 200
    implicitHeight: Theme.controlHeight
    radius: Theme.radius
    color: Theme.field
    border.color: activeFocus ? Theme.accent : hover.hovered ? Theme.borderHover : Theme.borderStrong
    border.width: activeFocus ? 2 : 1
    opacity: enabled ? 1 : Theme.disabledOpacity
    activeFocusOnTab: true

    Label {
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: !root.capturing ? Format.hotkey(root.combo) : root.refusal !== "" ? root.refusal : "press the keys"
        color: root.capturing ? Theme.muted : Theme.text
    }
    Caption {
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        visible: root.capturing
        text: "Esc"
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: root.forceActiveFocus() }

    // The hotkeys come back when the field lets go: on focus out, and also
    // when the field goes away while recording (a click on another page in
    // the side navigation takes no focus, it only unloads this page).
    onCapturingChanged: {
        refusal = ""
        backend.setHotkeyCapture(capturing)
    }
    Component.onDestruction: if (capturing) backend.setHotkeyCapture(false)

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Backtab || (event.key === Qt.Key_Tab && event.modifiers === Qt.NoModifier)) {
            event.accepted = false  // keyboard navigation, not a hotkey
            return
        }
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
        } else if ([Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta].indexOf(event.key) < 0) {
            // Without Ctrl, Alt or Win a letter would be taken from every program; with
            // one held, the key itself is one a hotkey cannot use (Ä, a dead key...).
            const held = event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
            root.refusal = held ? "that key cannot be a hotkey" : "add Ctrl, Alt or Win"
        }
    }
}
