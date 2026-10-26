import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Icons.js" as Icons

// Saved profiles: pick one to load, or save the current settings under a name.
Popup {
    id: root
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    anchors.centerIn: Overlay.overlay
    width: 420
    padding: 3 * Theme.space
    background: Rectangle { color: Theme.card; border.color: Theme.borderStrong }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.6) }

    contentItem: ColumnLayout {
        spacing: 2 * Theme.space
        Text { text: "Profiles"; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.sizeTitle; font.weight: Font.DemiBold }
        Text {
            text: "One per game: its window, area, languages and look. The one whose window title matches loads on its own."
            color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.min(Math.max(list.contentHeight, 36), 220) + 2
            color: Theme.field
            border.color: Theme.border
            ListView {
                id: list
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: backend.profiles
                delegate: Rectangle {
                    required property string modelData
                    readonly property bool active: modelData === backend.profileName
                    width: list.width
                    height: 36
                    color: active ? Theme.accentSoft : hover.containsMouse ? Theme.cardRaised : "transparent"
                    Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; path: Icons.folder; color: parent.active ? Theme.accent : Theme.muted; size: 16 }
                    Text { x: 36; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.size }
                    MouseArea {
                        id: hover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { backend.loadProfile(parent.modelData); root.close() }
                    }
                }
                Text {
                    visible: list.count === 0
                    anchors.centerIn: parent
                    text: "none saved yet"
                    color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space
            Field { id: name; placeholderText: "name (default: the game)"; Layout.fillWidth: true }
            SecondaryButton {
                text: "Save current as"
                icon_: Icons.check
                onClicked: { backend.saveProfile(name.text); name.text = ""; root.close() }
            }
        }
    }
}
