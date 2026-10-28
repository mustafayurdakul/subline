import QtQuick
import "Icons.js" as Icons

// One line of trouble, until dismissed.
Rectangle {
    id: root
    property string text: ""
    signal dismissed()

    visible: text !== ""
    implicitHeight: Math.max(40, message.implicitHeight + 16)
    radius: Theme.radius
    color: Theme.card
    border.color: Theme.danger

    Label {
        id: message
        anchors.left: parent.left
        anchors.right: closeButton.left
        anchors.leftMargin: 2 * Theme.space
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        wrapMode: Text.WordWrap
    }
    Item {
        id: closeButton
        anchors.right: parent.right
        width: 40; height: parent.height
        activeFocusOnTab: true
        Keys.onReturnPressed: root.dismissed()
        Keys.onSpacePressed: root.dismissed()
        Rectangle {
            anchors.centerIn: parent
            width: 28; height: 28
            radius: Theme.radius
            color: tap.pressed ? Theme.cardPressed : hover.hovered ? Theme.cardRaised : "transparent"
            FocusRing { visible: closeButton.activeFocus; gap: 0 }
            Icon { anchors.centerIn: parent; path: Icons.close; color: Theme.muted; size: 16 }
        }
        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tap; onTapped: root.dismissed() }
    }
}
