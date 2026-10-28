import QtQuick
import QtQuick.Controls.Basic as C

// A quiet button: outline on the card colour; darker while held down.
C.Button {
    id: root
    property string icon_: ""
    property bool danger: false

    implicitHeight: Theme.controlHeight
    leftPadding: 14
    rightPadding: 14
    font.family: Theme.font
    font.pixelSize: Theme.size
    opacity: enabled ? 1 : Theme.disabledOpacity

    background: Rectangle {
        radius: Theme.radius
        color: root.down ? Theme.cardPressed : root.hovered ? Theme.cardRaised : Theme.card
        border.color: root.danger ? Theme.danger : root.hovered ? Theme.borderHover : Theme.borderStrong
        FocusRing { visible: root.visualFocus }
    }
    contentItem: Row {
        spacing: 8
        Icon {
            visible: root.icon_ !== ""
            path: root.icon_
            color: root.danger ? Theme.danger : Theme.textSoft
            size: 16
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.text
            color: root.danger ? Theme.danger : Theme.text
            font: root.font
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
