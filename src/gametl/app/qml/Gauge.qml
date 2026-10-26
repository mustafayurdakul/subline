import QtQuick
import QtQuick.Controls.Basic

// A slider with the value shown beside it, bound to `map[key]`; `scale`
// shows a 0..1 setting as 0..100.
Row {
    id: root
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property int decimals: 0
    property real scale: 1
    property string suffix: ""
    property string specialText: ""  // shown at `from`
    property var map: backend.settings
    property string key: ""
    readonly property real value: Number(map[key]) * scale
    spacing: Theme.space + 2

    Slider {
        id: slider
        width: 160
        height: 24
        from: root.from; to: root.to; stepSize: root.stepSize
        snapMode: Slider.SnapAlways
        value: root.value
        onMoved: root.map[root.key] = Math.round(value / root.scale * 1000) / 1000

        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth
            height: 4
            color: Theme.borderStrong
            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                color: Theme.accent
            }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: 14; height: 14
            color: Theme.text
            border.color: Theme.window
            border.width: 2
        }
    }
    Label {
        anchors.verticalCenter: parent.verticalCenter
        width: 56
        text: root.value === root.from && root.specialText !== "" ? root.specialText : root.value.toFixed(root.decimals) + root.suffix
        color: Theme.textSoft
        font.pixelSize: Theme.sizeCaption
    }
}
