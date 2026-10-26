import QtQuick
import QtQuick.Controls.Basic

// A segmented control for a small set of exclusive choices.
Rectangle {
    id: root
    property var options: []
    property int current: 0
    signal picked(int index)

    implicitWidth: row.implicitWidth + 2 * 3
    implicitHeight: 32
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: Theme.border

    Row {
        id: row
        x: 3; y: 3
        spacing: 2
        Repeater {
            model: root.options
            delegate: Rectangle {
                required property int index
                required property string modelData
                readonly property bool active: index === root.current
                width: label.implicitWidth + 2 * 12
                height: 26
                radius: Theme.radiusSmall - 2
                color: active ? Theme.cardRaised : "transparent"
                border.color: active ? Theme.borderStrong : "transparent"
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: modelData
                    color: parent.active ? Theme.text : Theme.muted
                    font.family: Theme.font
                    font.pixelSize: Theme.sizeSmall + 1
                    font.weight: parent.active ? Font.DemiBold : Font.Normal
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { root.current = parent.index; root.picked(parent.index) }
                }
            }
        }
    }
}
