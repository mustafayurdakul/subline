import QtQuick
import QtQuick.Controls.Basic

// A slider with the value shown beside it.
Row {
    id: root
    property real value: 0
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property string suffix: ""
    property string specialText: ""  // shown at `from`
    spacing: Theme.space + 2

    Slider {
        id: slider
        width: 160
        height: 24
        from: root.from; to: root.to; stepSize: root.stepSize
        value: root.value
        onMoved: root.value = value

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
        text: root.value === root.from && root.specialText !== "" ? root.specialText : Math.round(root.value) + root.suffix
        color: Theme.textSoft
        font.family: Theme.font
        font.pixelSize: Theme.sizeSmall + 1
    }
}
