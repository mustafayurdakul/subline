import QtQuick
import "Icons.js" as Icons

// One line of trouble, until dismissed.
Rectangle {
    id: root
    property string text: ""
    signal dismissed()

    visible: text !== ""
    implicitHeight: visible ? Math.max(40, message.implicitHeight + 16) : 0
    color: Theme.card
    border.color: Theme.danger

    Text {
        id: message
        anchors.left: parent.left
        anchors.right: closeButton.left
        anchors.leftMargin: 2 * Theme.space
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.size
        wrapMode: Text.WordWrap
    }
    Item {
        id: closeButton
        anchors.right: parent.right
        width: 40; height: parent.height
        Icon { anchors.centerIn: parent; path: Icons.close; color: Theme.muted; size: 16 }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.dismissed() }
    }
}
