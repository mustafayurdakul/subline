import QtQuick
import QtQuick.Controls.Basic as C

// The one filled button on a page, in the accent. (Controls is imported
// under a name so that Label and Dialog stay the app's own.)
C.Button {
    id: root
    property string icon_: ""
    property color fill: Theme.accent

    implicitHeight: Theme.controlHeight
    leftPadding: 16
    rightPadding: 16
    font.family: Theme.font
    font.pixelSize: Theme.size
    font.weight: Font.DemiBold
    opacity: enabled ? 1 : Theme.disabledOpacity

    background: Rectangle {
        radius: Theme.radius
        color: root.down ? Qt.darker(root.fill, 1.2) : root.hovered ? Qt.lighter(root.fill, 1.1) : root.fill
        FocusRing { visible: root.visualFocus }
    }
    contentItem: Row {
        spacing: 8
        Icon { visible: root.icon_ !== ""; path: root.icon_; color: Theme.textOnAccent; size: 16; strokeWidth: 2.2; anchors.verticalCenter: parent.verticalCenter }
        Text { text: root.text; color: Theme.textOnAccent; font: root.font; anchors.verticalCenter: parent.verticalCenter }
    }
}
