import QtQuick
import QtQuick.Controls.Basic

// A switch: a pill that fills with the accent colour when on.
Switch {
    id: root
    implicitWidth: 44
    implicitHeight: 24
    padding: 0

    indicator: Rectangle {
        width: 44; height: 24; radius: 12
        color: root.checked ? Theme.accent : Theme.borderStrong
        border.color: root.checked ? Theme.accent : Theme.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            width: 18; height: 18; radius: 9
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: "#FFFFFF"
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
    contentItem: Item {}
}
