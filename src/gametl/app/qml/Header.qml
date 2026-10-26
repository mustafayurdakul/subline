import QtQuick
import "Icons.js" as Icons

// Page title on the left; the overlay's one button on the right. A visible
// Stop button is the running indicator; there is no separate status text.
// The button's right edge lines up with the cards below, so the row is
// anchored, not laid out: layouts gave the hidden button slack.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property string status: "idle"  // "idle" | "starting" | "running" | "paused"

    implicitHeight: 72
    readonly property int margin: 4 * Theme.space
    readonly property int rowWidth: Math.min(Theme.contentWidth, width - 2 * margin)

    Column {
        x: root.margin
        anchors.verticalCenter: parent.verticalCenter
        width: root.rowWidth - buttons.width - 2 * Theme.space
        spacing: 2
        Text { text: root.title; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.sizeHeading; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
        Text { text: root.subtitle; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1; visible: root.subtitle !== ""; elide: Text.ElideRight; width: parent.width }
    }

    Item {
        id: buttons
        x: root.margin + root.rowWidth - width
        anchors.verticalCenter: parent.verticalCenter
        width: root.status === "idle" ? start.implicitWidth : stop.implicitWidth
        height: Math.max(start.implicitHeight, stop.implicitHeight)

        PrimaryButton {
            id: start
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: root.status === "idle"
            text: "Start"
            icon_: Icons.play
            onClicked: backend.start()
        }
        SecondaryButton {
            id: stop
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: root.status !== "idle"
            text: root.status === "starting" ? "Cancel" : "Stop"
            icon_: Icons.stop
            onClicked: backend.stop()
        }
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
}
