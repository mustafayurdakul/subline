import QtQuick
import QtQuick.Controls.Basic

// A number with minus and plus buttons; `specialText` shows for `from`.
// With `map` and `key` it follows and writes that settings entry.
Rectangle {
    id: root
    property real value: 0
    property int from: 0
    property int to: 100
    property int step: 1
    property string suffix: ""
    property string specialText: ""
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""

    implicitWidth: 132
    implicitHeight: 32
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: Theme.border

    Binding on value { when: root.bound; value: root.bound ? Number(root.map[root.key]) : 0 }

    function change(delta) {
        var next = Math.min(root.to, Math.max(root.from, Math.round(root.value) + delta))
        if (bound)
            map[key] = next
        else
            value = next
    }

    Row {
        anchors.fill: parent
        Rectangle {
            width: 32; height: parent.height; color: "transparent"
            Text { anchors.centerIn: parent; text: "−"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: 16 }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.change(-root.step) }
        }
        Rectangle {
            width: root.width - 64; height: parent.height; color: "transparent"
            Text {
                anchors.centerIn: parent
                text: root.value === root.from && root.specialText !== "" ? root.specialText : Math.round(root.value) + root.suffix
                color: Theme.text
                font.family: Theme.font
                font.pixelSize: Theme.sizeSmall + 1
            }
        }
        Rectangle {
            width: 32; height: parent.height; color: "transparent"
            Text { anchors.centerIn: parent; text: "+"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: 16 }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.change(root.step) }
        }
    }
}
