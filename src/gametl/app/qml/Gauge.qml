import QtQuick
import QtQuick.Controls.Basic

// A slider with the value shown beside it. With `map` and `key` it follows
// and writes that settings entry; `scale` shows a 0..1 setting as 0..100.
Row {
    id: root
    property real value: 0
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property int decimals: 0
    property real scale: 1
    property string suffix: ""
    property string specialText: ""  // shown at `from`
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""
    spacing: Theme.space + 2

    Binding on value { when: root.bound; value: root.bound ? Number(root.map[root.key]) * root.scale : 0 }

    Slider {
        id: slider
        width: 160
        height: 24
        from: root.from; to: root.to; stepSize: root.stepSize
        value: root.value
        onMoved: {
            var shown = Math.round(value / root.stepSize) * root.stepSize
            if (root.bound)
                root.map[root.key] = Math.round(shown / root.scale * 1000) / 1000
            else
                root.value = shown
        }

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
    Text {
        anchors.verticalCenter: parent.verticalCenter
        width: 56
        text: root.value === root.from && root.specialText !== "" ? root.specialText : root.value.toFixed(root.decimals) + root.suffix
        color: Theme.textSoft
        font.family: Theme.font
        font.pixelSize: Theme.sizeSmall + 1
    }
}
