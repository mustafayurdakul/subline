import QtQuick

// A segmented control for a small set of exclusive choices: `options` are
// the labels, `values` the settings values they stand for, written to
// `map[key]`. A value outside `values` leaves no segment lit.
Rectangle {
    id: root
    property var options: []
    property var values: []
    property var map: backend.settings
    property string key: ""
    readonly property int current: values.indexOf(map[key])

    implicitWidth: row.implicitWidth + 2 * 3
    implicitHeight: 32
    radius: Theme.radius
    color: Theme.field
    border.color: Theme.border

    Row {
        id: row
        x: 3; y: 3
        spacing: 2
        Repeater {
            model: root.options
            delegate: Rectangle {
                id: segment
                required property int index
                required property string modelData
                readonly property bool active: index === root.current
                width: label.implicitWidth + 2 * 12
                height: 26
                radius: Theme.radius
                color: active ? Theme.cardRaised : "transparent"
                border.color: active ? Theme.borderStrong : "transparent"
                Label {
                    id: label
                    anchors.centerIn: parent
                    text: segment.modelData
                    color: segment.active ? Theme.text : Theme.muted
                    font.pixelSize: Theme.sizeCaption
                    font.weight: segment.active ? Font.DemiBold : Font.Normal
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.map[root.key] = root.values[segment.index]
                }
            }
        }
    }
}
