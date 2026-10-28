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

    // A clickable rail entry: hover and press tints, Tab reaches it, Enter
    // or Space acts. A click takes the focus first, so a field typed in and
    // written only when left (`live: false`) writes before its page goes.
    component NavItem: Rectangle {
        id: item
        signal activated()
        readonly property bool hovered: hover.hovered
        readonly property bool pressed: tap.pressed
        radius: Theme.radius
        activeFocusOnTab: true
        Keys.onReturnPressed: activated()
        Keys.onEnterPressed: activated()
        Keys.onSpacePressed: activated()
        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tap; onTapped: { item.forceActiveFocus(); item.activated() } }
        FocusRing { visible: item.activeFocus; gap: 0; radius: Theme.radius }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 2 * Theme.space
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 2 * Theme.space
            spacing: 10
            // The mark: a window frame with the subtitle strip along its
            // bottom. app/icon.py draws the same shape for the tray and the
            // title bar, on a dark tile, in the overlay's state colours.
            Item {
                width: 30; height: 30
                Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.accent; border.width: 2 }
                Rectangle { x: 7; y: 19; width: 16; height: 4; color: Theme.accent }
            }
            ColumnLayout {
                spacing: 0
                Label { text: backend.appName; font.pixelSize: Theme.sizeBrand; font.weight: Font.DemiBold }
                Caption { text: backend.version }
            }
        }

        Repeater {
            model: root.pages
            delegate: NavItem {
                id: entry
                required property var modelData
                readonly property bool active: modelData.key === root.current
                Layout.fillWidth: true
                height: 36
                color: active ? Theme.accentSoft : pressed ? Theme.cardPressed : hovered ? Theme.card : "transparent"
                onActivated: root.navigate(entry.modelData.key)

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
            }
        }

        Item { Layout.fillHeight: true }

        // The overlay's last status line, as the tray shows it. Home has
        // its own status line under the Start button, so not there.
        Caption {
            Layout.fillWidth: true
            Layout.bottomMargin: Theme.space
            visible: backend.statusText !== "" && root.current !== "home"
            text: backend.statusText
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        NavItem {
            Layout.fillWidth: true
            height: 56
            color: pressed ? Theme.cardPressed : hovered ? Theme.cardRaised : Theme.card
            border.color: Theme.border
            onActivated: root.profileClicked()
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
        }
    }
}
