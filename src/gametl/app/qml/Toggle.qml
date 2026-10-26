import QtQuick
import QtQuick.Controls.Basic

// A switch: a square knob sliding on a bar; the bar takes the accent when
// on. With `map` and `key` it follows and writes that settings entry.
Switch {
    id: root
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""

    implicitWidth: 44
    implicitHeight: 22
    padding: 0

    Binding on checked { when: root.bound; value: root.bound ? Boolean(root.map[root.key]) : false }
    onToggled: if (bound) map[key] = checked

    indicator: Rectangle {
        width: 44; height: 22
        color: root.checked ? Theme.accent : Theme.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            width: 16; height: 16
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: root.checked ? Theme.textOnAccent : Theme.text
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
    contentItem: Item {}
}
