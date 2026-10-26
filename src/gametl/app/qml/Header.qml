import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Page title on the left; the live status and the Start/Stop button on the right.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property string status: "idle"  // "idle" | "starting" | "running" | "paused"
    property string statusText: "Idle"

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

        Rectangle {
            height: 30
            width: chip.implicitWidth + 24
            radius: 15
            color: Theme.card
            border.color: Theme.border
            Row {
                id: chip
                anchors.centerIn: parent
                spacing: 8
                Rectangle {
                    width: 8; height: 8; radius: 4
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.status === "running" ? Theme.success
                         : root.status === "starting" ? Theme.accent
                         : root.status === "paused" ? Theme.warning : Theme.muted
                }
                Text { text: root.statusText; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1; anchors.verticalCenter: parent.verticalCenter }
            }
        }

        PrimaryButton {
            text: root.status === "running" ? "Stop" : root.status === "starting" ? "Cancel" : "Start"
            icon_: root.status === "running" ? Icons.stop : Icons.play
            fill: root.status === "running" ? Theme.danger : Theme.accent
        }
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
}
