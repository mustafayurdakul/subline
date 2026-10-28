import QtQuick
import QtQuick.Controls.Basic

// A quiet button: outline on the card colour.
Button {
    id: root
    property string icon_: ""
    property bool danger: false

    implicitHeight: 34
    leftPadding: 14
    rightPadding: 14
    font.family: Theme.font
    font.pixelSize: Theme.size

    background: Rectangle {
        radius: Theme.radius
        color: root.down ? Theme.cardRaised : root.hovered ? Theme.cardRaised : Theme.card
        border.color: root.danger ? Theme.danger : Theme.borderStrong
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
