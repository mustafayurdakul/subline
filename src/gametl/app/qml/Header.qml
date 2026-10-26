import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Page title on the left; the state of the overlay, in words, and its one button on the right.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property string status: "idle"  // "idle" | "starting" | "running" | "paused"
    property string statusText: "Overlay off"

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
            height: 32
            width: chip.implicitWidth + 28
            color: root.status === "running" ? Theme.accentSoft : Theme.card
            border.color: root.status === "running" ? Theme.accentDeep : Theme.border
            Text {
                id: chip
                anchors.centerIn: parent
                text: root.statusText
                color: root.status === "running" ? Theme.text : Theme.textSoft
                font.family: Theme.font
                font.pixelSize: Theme.sizeSmall + 1
            }
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
