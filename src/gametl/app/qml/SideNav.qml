import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// The left rail: app name, pages, the overlay's last word, and the profile at the bottom.
Rectangle {
    id: root
    property var pages: []  // Main's page table: key, label, icon
    property string current: ""
    signal navigate(string page)
    signal profileClicked()

    width: Theme.sidebarWidth
    color: Theme.sidebar

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 2 * Theme.space
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 2 * Theme.space
            spacing: 10
            // The mark: a window frame with the subtitle strip along its
            // bottom (app/icon.py draws the same for the tray).
            Item {
                width: 30; height: 30
                Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.accent; border.width: 2 }
                Rectangle { x: 7; y: 19; width: 16; height: 4; color: Theme.accent }
            }
            ColumnLayout {
                spacing: 0
                Label { text: backend.appName; font.pixelSize: 16; font.weight: Font.DemiBold }
                Caption { text: backend.version }
            }
        }

        Repeater {
            model: root.pages
            delegate: Rectangle {
                id: entry
                required property var modelData
                readonly property bool active: modelData.key === root.current
                Layout.fillWidth: true
                height: 36
                radius: Theme.radius
                color: active ? Theme.accentSoft : mouse.containsMouse ? Theme.card : "transparent"

                Rectangle { visible: entry.active; x: 0; y: 9; width: 3; height: parent.height - 18; radius: 1.5; color: Theme.accent }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 14
                    spacing: 10
                    Icon { path: entry.modelData.icon; color: entry.active ? Theme.accent : Theme.muted; size: 18; anchors.verticalCenter: parent.verticalCenter }
                    Label {
                        text: entry.modelData.label
                        color: entry.active ? Theme.text : Theme.textSoft
                        font.weight: entry.active ? Font.DemiBold : Font.Normal
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.navigate(entry.modelData.key)
                }
            }
        }

        Item { Layout.fillHeight: true }

        // The overlay's last status line, as the tray shows it.
        Caption {
            Layout.fillWidth: true
            Layout.bottomMargin: Theme.space
            visible: backend.statusText !== ""
            text: backend.statusText
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        Rectangle {
            Layout.fillWidth: true
            height: 56
            radius: Theme.radius
            color: profileMouse.containsMouse ? Theme.cardRaised : Theme.card
            border.color: Theme.border
            Icon { id: folder; x: 12; anchors.verticalCenter: parent.verticalCenter; path: Icons.folder; color: Theme.muted; size: 18 }
            Column {
                anchors.left: folder.right
                anchors.right: chevron.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Caption { text: "Profile" }
                Label {
                    width: parent.width
                    text: backend.profileName !== "" ? backend.profileName : "not saved"
                    color: backend.profileName !== "" ? Theme.text : Theme.muted
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
            }
            Icon { id: chevron; path: Icons.chevron; color: Theme.muted; size: 16; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter }
            MouseArea {
                id: profileMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.profileClicked()
            }
        }
    }
}
