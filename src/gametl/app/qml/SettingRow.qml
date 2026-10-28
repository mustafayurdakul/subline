import QtQuick
import QtQuick.Layouts

// One setting: label and helper on the left, the control pinned to the
// right. Beside an ordinary control the label is centred; beside a tall one
// (a multi-line field) it sits at the top, level with the first line.
Item {
    id: root
    property string label: ""
    property string helper: ""
    default property alias control: controls.data
    readonly property bool tall: controls.implicitHeight > labels.implicitHeight + 2 * Theme.space

    Layout.fillWidth: true
    implicitHeight: Math.max(labels.implicitHeight, controls.implicitHeight)

    Column {
        id: labels
        anchors.left: parent.left
        anchors.right: controls.left
        anchors.rightMargin: 2 * Theme.space
        y: root.tall ? 6 : (root.height - height) / 2
        spacing: 2
        Label { width: parent.width; text: root.label; wrapMode: Text.WordWrap }
        Caption { width: parent.width; visible: root.helper !== ""; text: root.helper }
    }

    Row {
        id: controls
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space
    }
}
