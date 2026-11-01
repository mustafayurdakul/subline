import QtQuick
import QtQuick.Controls.Basic as C
import QtQuick.Layouts
import "Icons.js" as Icons

// Saved profiles: pick one to load, delete one, or save the current settings under a name.
Dialog {
    id: root
    title: "Profiles"
    closePolicy: C.Popup.CloseOnEscape | C.Popup.CloseOnPressOutside

    Caption {
        Layout.fillWidth: true
        text: "One per game: its window, area, languages and look. The one whose window title matches loads on its own."
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.min(Math.max(list.contentHeight, 36), 220) + 2
        radius: Theme.radius
        color: Theme.field
        border.color: Theme.borderStrong
        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: backend.profiles
            C.ScrollBar.vertical: ThinScrollBar { }
            // Tab reaches the list; the arrow keys pick a profile, Enter loads it, Delete asks to delete it.
            activeFocusOnTab: true
            function load(name) { backend.loadProfile(name); root.close() }
            function askDelete(name) { confirmDelete.profile = name; confirmDelete.open() }
            Keys.onReturnPressed: if (currentIndex >= 0) load(model[currentIndex])
            Keys.onEnterPressed: if (currentIndex >= 0) load(model[currentIndex])
            Keys.onDeletePressed: if (currentIndex >= 0) askDelete(model[currentIndex])
            delegate: Rectangle {
                id: row
                required property string modelData
                readonly property bool active: modelData === backend.profileName
                width: list.width
                height: 36
                radius: Theme.radius - 1
                color: active ? Theme.accentSoft : tap.pressed ? Theme.cardPressed : hover.hovered ? Theme.cardRaised : "transparent"
                border.color: Theme.accent
                border.width: row.ListView.isCurrentItem && list.activeFocus ? 2 : 0
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                // The row loads the profile; the bin at its end is kept out of that, so a press there only deletes.
                Item {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom; right: remove.left }
                    TapHandler { id: tap; onTapped: list.load(row.modelData) }
                }
                Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; path: Icons.folder; color: row.active ? Theme.accent : Theme.muted; size: 16 }
                Label { x: 36; width: remove.x - x - Theme.space; anchors.verticalCenter: parent.verticalCenter; text: row.modelData; elide: Text.ElideRight }
                C.AbstractButton {
                    id: remove
                    anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter }
                    width: 28; height: 28
                    padding: 6  // the icon stays 16 px; the rest is a larger target
                    focusPolicy: Qt.NoFocus  // the list's Delete key does this from the keyboard
                    Accessible.name: "Delete " + row.modelData
                    onClicked: list.askDelete(row.modelData)
                    background: Rectangle {
                        radius: Theme.radius - 2
                        color: remove.down ? Theme.cardPressed : remove.hovered ? Theme.cardRaised : "transparent"
                    }
                    contentItem: Icon {
                        path: Icons.trash
                        size: 16
                        color: remove.hovered ? Theme.danger : Theme.muted
                    }
                }
            }
            Caption { visible: list.count === 0; anchors.centerIn: parent; text: "none saved yet"; font.pixelSize: Theme.sizeCaption }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space
        Field { id: name; placeholderText: "name (default: the game)"; Layout.fillWidth: true; onAccepted: save.clicked() }
        SecondaryButton {
            id: save
            text: "Save current as"
            icon_: Icons.check
            onClicked: if (backend.saveProfile(name.text)) { name.text = ""; root.close() }  // kept open on a problem
        }
    }

    Confirm {
        id: confirmDelete
        property string profile: ""
        title: "Delete this profile?"
        text: "The profile " + profile + " is deleted from this computer. The settings shown now stay as they are."
        confirmText: "Delete"
        onConfirmed: backend.deleteProfile(profile)
    }
}
