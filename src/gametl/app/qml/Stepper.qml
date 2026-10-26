import QtQuick

// A number with minus and plus buttons, bound to `map[key]`; `specialText`
// shows for `from`.
Rectangle {
    id: root
    property int from: 0
    property int to: 100
    property int step: 1
    property string suffix: ""
    property string specialText: ""
    property var map: backend.settings
    property string key: ""
    readonly property real value: Number(map[key])

    implicitWidth: 132
    implicitHeight: 32
    radius: Theme.radius
    color: Theme.field
    border.color: Theme.border

    function change(delta) {
        map[key] = Math.min(root.to, Math.max(root.from, Math.round(root.value) + delta))
    }

    component StepButton: Item {
        property string glyph
        property int delta
        width: 32; height: root.height
        Label { anchors.centerIn: parent; text: parent.glyph; color: Theme.textSoft; font.pixelSize: 16 }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.change(parent.delta) }
    }

    Row {
        anchors.fill: parent
        StepButton { glyph: "−"; delta: -root.step }
        Item {
            width: root.width - 64; height: root.height
            Label {
                anchors.centerIn: parent
                text: root.value === root.from && root.specialText !== "" ? root.specialText : Math.round(root.value) + root.suffix
                font.pixelSize: Theme.sizeCaption
            }
        }
        StepButton { glyph: "+"; delta: root.step }
    }
}
