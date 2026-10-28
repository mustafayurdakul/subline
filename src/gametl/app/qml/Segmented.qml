import QtQuick

// A segmented control for a small set of exclusive choices: `options` are
// the labels, `values` the settings values they stand for, written to
// `map[key]`. A value outside `values` leaves no segment lit. Tab reaches
// it; the arrow keys move the choice.
Rectangle {
    id: root
    property var options: []
    property var values: []
    property var map: backend.settings
    property string key: ""
    readonly property int current: values.indexOf(map[key])
    readonly property int inset: 3

    implicitWidth: row.implicitWidth + 2 * inset
    implicitHeight: Theme.controlHeight
    radius: Theme.radius
    color: Theme.field
    border.color: Theme.borderStrong
    opacity: enabled ? 1 : Theme.disabledOpacity
    activeFocusOnTab: true

    function choose(index) {
        if (index >= 0 && index < values.length)
            map[key] = values[index]
    }
    Keys.onLeftPressed: choose(Math.max(0, current - 1))
    Keys.onRightPressed: choose(Math.min(values.length - 1, current + 1))

    FocusRing { visible: root.activeFocus }

    Row {
        id: row
        x: root.inset; y: root.inset
        spacing: 2
        Repeater {
            model: root.options
            delegate: Rectangle {
                id: segment
                required property int index
                required property string modelData
                readonly property bool active: index === root.current
                width: label.implicitWidth + 2 * 12
                height: root.height - 2 * root.inset
                radius: Theme.radius - 2
                color: active ? Theme.accentSoft : tap.pressed ? Theme.cardPressed : hover.hovered ? Theme.cardRaised : "transparent"
                Label {
                    id: label
                    anchors.centerIn: parent
                    text: segment.modelData
                    color: segment.active ? Theme.accent : hover.hovered ? Theme.text : Theme.muted
                    font.pixelSize: Theme.sizeCaption
                    font.weight: segment.active ? Font.DemiBold : Font.Normal
                }
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { id: tap; onTapped: root.choose(segment.index) }
            }
        }
    }
}
