import QtQuick
import QtQuick.Controls.Basic

// A number with minus and plus buttons; `specialText` shows for `from`.
Rectangle {
    id: root
    property int value: 0
    property int from: 0
    property int to: 100
    property int step: 1
    property string suffix: ""
    property string specialText: ""

    implicitWidth: 132
    implicitHeight: 32
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: Theme.border

    Row {
        anchors.fill: parent
        Rectangle {
            width: 32; height: parent.height; color: "transparent"
            Text { anchors.centerIn: parent; text: "−"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: 16 }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.value = Math.max(root.from, root.value - root.step) }
        }
        Rectangle {
            width: root.width - 64; height: parent.height; color: "transparent"
            Text {
                anchors.centerIn: parent
                text: root.value === root.from && root.specialText !== "" ? root.specialText : root.value + root.suffix
                color: Theme.text
                font.family: Theme.font
                font.pixelSize: Theme.sizeSmall + 1
            }
        }
        Rectangle {
            width: 32; height: parent.height; color: "transparent"
            Text { anchors.centerIn: parent; text: "+"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: 16 }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.value = Math.min(root.to, root.value + root.step) }
        }
    }
}
