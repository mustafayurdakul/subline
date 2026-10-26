import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// The left rail: app name, pages, and the profile at the bottom.
Rectangle {
    id: root
    property string current: "firstrun"
    property string profileName: "Alan Wake 2"
    signal navigate(string page)

    readonly property var entries: [
        { key: "firstrun", label: "Set up", icon: Icons.sparkles },
        { key: "game", label: "Game", icon: Icons.gamepad },
        { key: "translation", label: "Translation", icon: Icons.translate },
        { key: "appearance", label: "Appearance", icon: Icons.palette },
        { key: "hotkeys", label: "Hotkeys", icon: Icons.keyboard },
        { key: "licence", label: "Licence", icon: Icons.key },
        { key: "advanced", label: "Advanced", icon: Icons.sliders },
    ]

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
            Rectangle {
                width: 30; height: 30
                color: Theme.accent
                Text { anchors.centerIn: parent; text: "T"; color: Theme.textOnAccent; font.family: Theme.font; font.pixelSize: 16; font.weight: Font.Bold }
            }
            ColumnLayout {
                spacing: 0
                Text { text: "gametl"; color: Theme.text; font.family: Theme.font; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { text: "0.1.2"; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall }
            }
        }

        Repeater {
            model: root.entries
            delegate: Rectangle {
                required property var modelData
                readonly property bool active: modelData.key === root.current
                Layout.fillWidth: true
                height: 36
                radius: Theme.radiusSmall
                color: active ? Theme.accentSoft : mouse.containsMouse ? Theme.card : "transparent"

                Rectangle {
                    visible: parent.active
                    x: 0; y: 0; width: 3; height: parent.height
                    color: Theme.accent
                }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 14
                    spacing: 10
                    Icon { path: modelData.icon; color: parent.parent.active ? Theme.accent : Theme.muted; size: 18; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: modelData.label
                        color: parent.parent.active ? Theme.text : Theme.textSoft
                        font.family: Theme.font
                        font.pixelSize: Theme.size
                        font.weight: parent.parent.active ? Font.DemiBold : Font.Normal
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.navigate(parent.modelData.key)
                }
            }
        }

        Item { Layout.fillHeight: true }

        Rectangle {
            Layout.fillWidth: true
            height: 56
            radius: Theme.radiusSmall
            color: Theme.card
            border.color: Theme.border
            Row {
                anchors.verticalCenter: parent.verticalCenter
                x: 12
                spacing: 10
                Icon { path: Icons.folder; color: Theme.muted; size: 18; anchors.verticalCenter: parent.verticalCenter }
                Column {
                    spacing: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Text { text: "Profile"; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall }
                    Text { text: root.profileName; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.size; font.weight: Font.DemiBold }
                }
            }
            Icon { path: Icons.chevron; color: Theme.muted; size: 16; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
