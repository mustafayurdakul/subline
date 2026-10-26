import QtQuick
import QtQuick.Controls.Basic

// A segmented control for a small set of exclusive choices. `options` are
// the labels; `values`, when given, the settings values they stand for,
// written to `map[key]`. A value outside `values` leaves no segment lit.
Rectangle {
    id: root
    property var options: []
    property var values: []
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== "" && values.length > 0
    property int current: 0
    signal picked(int index)

    implicitWidth: row.implicitWidth + 2 * 3
    implicitHeight: 32
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: Theme.border

    Binding on current { when: root.bound; value: root.bound ? root.values.indexOf(root.map[root.key]) : 0 }

    function choose(index) {
        if (bound)
            map[key] = values[index]
        else
            current = index
        picked(index)
    }

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
                radius: Theme.radiusSmall
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
                    onClicked: root.choose(parent.index)
                }
            }
        }
    }
}
