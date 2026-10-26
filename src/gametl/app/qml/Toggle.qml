import QtQuick
import QtQuick.Controls.Basic

// A switch: a square knob sliding on a bar; the bar takes the accent when on.
Switch {
    id: root
    implicitWidth: 44
    implicitHeight: 22
    padding: 0

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
