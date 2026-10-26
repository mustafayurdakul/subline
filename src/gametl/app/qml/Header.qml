import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Page title on the left; the overlay's one button on the right. A visible
// Stop button is the running indicator; there is no separate status text.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property string status: "idle"  // "idle" | "starting" | "running" | "paused"

    implicitHeight: 72

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 4 * Theme.space
        anchors.rightMargin: 4 * Theme.space
        spacing: 2 * Theme.space

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text { text: root.title; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.sizeHeading; font.weight: Font.DemiBold }
            Text { text: root.subtitle; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1; visible: root.subtitle !== "" }
        }

        PrimaryButton {
            visible: root.status === "idle"
            text: "Start"
            icon_: Icons.play
        }
        SecondaryButton {
            visible: root.status !== "idle"
            text: root.status === "starting" ? "Cancel" : "Stop"
            icon_: Icons.stop
        }
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
}
