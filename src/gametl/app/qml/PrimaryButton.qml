import QtQuick
import QtQuick.Controls.Basic

// The one accent-filled button on a page.
Button {
    id: root
    property string icon_: ""
    property color fill: Theme.accent

    implicitHeight: 36
    leftPadding: 16
    rightPadding: 16
    font.family: Theme.font
    font.pixelSize: Theme.size
    font.weight: Font.DemiBold

    background: Rectangle {
        radius: Theme.radiusSmall
        color: root.down ? Qt.darker(root.fill, 1.15) : root.hovered ? Qt.lighter(root.fill, 1.08) : root.fill
    }
    contentItem: Row {
        spacing: 8
        Icon { visible: root.icon_ !== ""; path: root.icon_; color: Theme.textOnAccent; size: 16; anchors.verticalCenter: parent.verticalCenter }
        Text { text: root.text; color: Theme.textOnAccent; font: root.font; anchors.verticalCenter: parent.verticalCenter }
    }
}
