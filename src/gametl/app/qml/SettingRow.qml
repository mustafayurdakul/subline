import QtQuick
import QtQuick.Layouts

// One setting: label and helper on the left, the control pinned to the right.
Item {
    id: root
    property string label: ""
    property string helper: ""
    default property alias control: controls.data

    Layout.fillWidth: true
    implicitHeight: Math.max(labels.implicitHeight, controls.implicitHeight) + 4

    Column {
        id: labels
        anchors.left: parent.left
        anchors.right: controls.left
        anchors.rightMargin: 2 * Theme.space
        anchors.verticalCenter: parent.verticalCenter
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
