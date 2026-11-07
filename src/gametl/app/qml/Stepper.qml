import QtQuick

// A number with minus and plus buttons, bound to `map[key]`; `specialText`
// shows for `from`. The first step up from that goes to `start` when it is
// set: a sensible value, where `from` plus one step is not. Tab reaches it;
// the arrow keys step it.
Rectangle {
    id: root
    property int from: 0
    property int to: 100
    property int step: 1
    property int start: from
    property string suffix: ""
    property string specialText: ""
    property var map: backend.settings
    property string key: ""
    readonly property real value: Number(map[key])

    implicitWidth: 132
    implicitHeight: Theme.controlHeight
    radius: Theme.radius
    color: Theme.field
    border.color: hover.hovered ? Theme.borderHover : Theme.borderStrong
    opacity: enabled ? 1 : Theme.disabledOpacity
    activeFocusOnTab: true

    function change(delta) {
        if (delta > 0 && root.specialText !== "" && Math.round(root.value) === root.from && root.start > root.from) {
            map[key] = root.start
            return
        }
        map[key] = Math.min(root.to, Math.max(root.from, Math.round(root.value) + delta))
    }

    Keys.onUpPressed: change(step)
    Keys.onRightPressed: change(step)
    Keys.onDownPressed: change(-step)
    Keys.onLeftPressed: change(-step)

    HoverHandler { id: hover }
    FocusRing { visible: root.activeFocus }

    component StepButton: Rectangle {
        id: button
        property string glyph
        property int delta
        readonly property bool limit: delta < 0 ? root.value <= root.from : root.value >= root.to
        width: 32; height: root.height
        radius: Theme.radius
        color: tap.pressed ? Theme.cardPressed : buttonHover.hovered && !limit ? Theme.cardRaised : "transparent"
        Label { anchors.centerIn: parent; text: button.glyph; color: button.limit ? Theme.borderStrong : Theme.textSoft; font.pixelSize: 16 }
        HoverHandler { id: buttonHover; cursorShape: button.limit ? Qt.ArrowCursor : Qt.PointingHandCursor }
        TapHandler { id: tap; onTapped: root.change(button.delta) }
    }

    Row {
        anchors.fill: parent
        anchors.margins: 1  // inside the edge
        StepButton { glyph: "−"; delta: -root.step }
        Item {
            width: root.width - 66; height: parent.height
            Label {
                anchors.centerIn: parent
                text: root.value === root.from && root.specialText !== "" ? root.specialText : Math.round(root.value) + root.suffix
                font.pixelSize: Theme.sizeCaption
            }
        }
        StepButton { glyph: "+"; delta: root.step }
    }
}
