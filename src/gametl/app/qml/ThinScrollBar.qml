import QtQuick
import QtQuick.Controls.Basic as C

// The scroll bar of the pages and the drop-down lists: thin and rounded,
// there only when something scrolls, brighter while in use. (A custom
// handle replaces the Basic style's own, and with it the logic that hid
// the bar when the content fits; `visible` puts that back.)
C.ScrollBar {
    id: root
    policy: C.ScrollBar.AsNeeded
    visible: size < 1.0
    padding: 2
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: root.pressed ? Theme.muted : Theme.borderStrong
        opacity: root.active || root.hovered ? 1 : 0.6
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }
}
