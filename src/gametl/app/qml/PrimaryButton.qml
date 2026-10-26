import QtQuick
import QtQuick.Controls.Basic

// The one filled button on a page: light on dark, no hue.
Button {
    id: root
    property string icon_: ""
    property color fill: Theme.primary

    implicitHeight: 36
    leftPadding: 16
    rightPadding: 16
    font.family: Theme.font
    font.pixelSize: Theme.size
    font.weight: Font.DemiBold

    background: Rectangle {
        radius: Theme.radiusSmall
        color: root.down ? Qt.darker(root.fill, 1.2) : root.hovered ? "#FFFFFF" : root.fill
    }
    contentItem: Row {
        spacing: 8
        Icon { visible: root.icon_ !== ""; path: root.icon_; color: Theme.textOnPrimary; size: 16; strokeWidth: 2.2; anchors.verticalCenter: parent.verticalCenter }
        Text { text: root.text; color: Theme.textOnPrimary; font: root.font; anchors.verticalCenter: parent.verticalCenter }
    }
}
