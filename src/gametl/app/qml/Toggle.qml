import QtQuick
import QtQuick.Controls.Basic

// A switch: light track with a dark knob when on, dark track with a light
// knob when off. No hue.
Switch {
    id: root
    implicitWidth: 44
    implicitHeight: 24
    padding: 0

    indicator: Rectangle {
        width: 44; height: 24; radius: 12
        color: root.checked ? Theme.primary : Theme.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            width: 18; height: 18; radius: 9
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: root.checked ? Theme.textOnPrimary : Theme.text
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
    contentItem: Item {}
}
