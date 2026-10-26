import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Icons.js" as Icons

// Saved profiles: pick one to load, or save the current settings under a name.
Dialog {
    id: root
    title: "Profiles"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    Caption {
        Layout.fillWidth: true
        text: "One per game: its window, area, languages and look. The one whose window title matches loads on its own."
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
                id: row
                required property string modelData
                readonly property bool active: modelData === backend.profileName
                width: list.width
                height: 36
                color: active ? Theme.accentSoft : hover.containsMouse ? Theme.cardRaised : "transparent"
                Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; path: Icons.folder; color: row.active ? Theme.accent : Theme.muted; size: 16 }
                Label { x: 36; anchors.verticalCenter: parent.verticalCenter; text: row.modelData }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { backend.loadProfile(row.modelData); root.close() }
                }
            }
            Caption { visible: list.count === 0; anchors.centerIn: parent; text: "none saved yet"; font.pixelSize: Theme.sizeCaption }
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
