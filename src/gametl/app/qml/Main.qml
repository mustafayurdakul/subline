import QtQuick
import QtQuick.Controls.Basic as C
import QtQuick.Layouts
import "Icons.js" as Icons

// The settings window's content: side navigation, header, the current page.
// The window sets two context properties: `backend` (a SettingsBackend),
// what the pages read and write, and `uiScale`, the screen's logical DPI
// over 96. Everything is laid out at 96 dpi and drawn `uiScale` times as
// large, so the window keeps its size and sharpness on a 150 % screen;
// popups, drawn above the page, take the same scale themselves.
Rectangle {
    id: root
    property string page: "home"
    // The window height at which the current page shows whole (for full-page renders).
    readonly property int fullHeight: Math.ceil((flick.y + flick.contentHeight) * uiScale)
    color: Theme.window

    // The one table the navigation, the header and the page loader read
    // (settings_window.PAGES lists the same keys; its check compares them).
    readonly property var pages: [
        { key: "home", label: "Home", subtitle: "", icon: Icons.home, source: "HomePage.qml" },
        { key: "game", label: "Game", subtitle: "Which window to read, and which part of it.", icon: Icons.gamepad, source: "GamePage.qml" },
        { key: "translation", label: "Translation", subtitle: "Languages, translator and keys.", icon: Icons.translate, source: "TranslationPage.qml" },
        { key: "appearance", label: "Appearance", subtitle: "How the subtitles look.", icon: Icons.palette, source: "AppearancePage.qml" },
        { key: "hotkeys", label: "Hotkeys", subtitle: "Global shortcuts; press the keys to set one.", icon: Icons.keyboard, source: "HotkeysPage.qml" },
        { key: "advanced", label: "Advanced", subtitle: "Timing, filters and the data on this computer.", icon: Icons.sliders, source: "AdvancedPage.qml" },
    ]
    readonly property var current: pages.find(function(p) { return p.key === root.page }) || pages[0]

    onPageChanged: flick.contentY = 0  // one Flickable shows every page: a new page opens at its top

    Item {
        width: root.width / uiScale
        height: root.height / uiScale
        scale: uiScale
        transformOrigin: Item.TopLeft

        RowLayout {
            anchors.fill: parent
            spacing: 0

            SideNav {
                Layout.fillHeight: true
                pages: root.pages
                current: root.page
                onNavigate: function(key) { root.page = key }
                onProfileClicked: profiles.open()
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Header {
                    Layout.fillWidth: true
                    visible: root.page !== "home"  // Home carries its own Start button
                    title: root.current.label
                    subtitle: root.current.subtitle
                    status: backend.status
                }

                Banner {
                    Layout.leftMargin: 4 * Theme.space
                    Layout.topMargin: 2 * Theme.space
                    Layout.preferredWidth: pageLoader.width
                    text: backend.problem
                    onDismissed: backend.clearProblem()
                }

                Flickable {
                    id: flick
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentHeight: pageLoader.height + 6 * Theme.space
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds  // a desktop page stops at its ends, no bounce
                    C.ScrollBar.vertical: ThinScrollBar { }

                    Loader {
                        id: pageLoader
                        x: 4 * Theme.space
                        y: 3 * Theme.space
                        width: Math.min(Theme.contentWidth, parent.width - 8 * Theme.space)
                        source: root.current.source
                    }
                }
            }
        }
    }

    ProfilePopup { id: profiles }
}
