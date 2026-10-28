import QtQuick
import QtQuick.Controls.Basic as C

// A slider with the value shown beside it, bound to `map[key]`. The slider
// shows the setting times `factor`: 100 shows a 0..1 share as a percentage,
// 100 / 255 an opacity byte.
Row {
    id: root
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property real factor: 1
    property string suffix: ""
    property string specialText: ""  // shown at `from`
    property var map: backend.settings
    property string key: ""
    readonly property real value: Number(map[key]) * factor
    spacing: Theme.space + 2
    opacity: enabled ? 1 : Theme.disabledOpacity

    C.Slider {
        id: slider
        width: 160
        height: 24
        from: root.from; to: root.to; stepSize: root.stepSize
        snapMode: C.Slider.SnapAlways
        value: root.value
        onMoved: root.map[root.key] = Math.round(value / root.factor * 1000) / 1000

        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth
            height: 4
            radius: 2
            color: Theme.borderStrong
            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: Theme.accent
            }
        }
        handle: Rectangle {
            readonly property int size: slider.pressed ? 14 : slider.hovered ? 18 : 16
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: size; height: size
            radius: size / 2
            color: Theme.accent
            border.color: Theme.card
            border.width: 3
            FocusRing { visible: slider.visualFocus; gap: 2; radius: parent.radius + gap }
        }
    }
    Label {
        anchors.verticalCenter: parent.verticalCenter
        width: 56
        text: root.value === root.from && root.specialText !== "" ? root.specialText : Math.round(root.value) + root.suffix
        color: Theme.textSoft
        font.pixelSize: Theme.sizeCaption
    }
}
