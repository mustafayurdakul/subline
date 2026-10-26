import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Icons.js" as Icons

// The settings window's content: side navigation, header, the current page.
// `backend` (a SettingsBackend, set as a context property by the window)
// is what the pages read and write.
Rectangle {
    id: root
    property string page: "firstrun"
    // The height at which the current page shows whole (for full-page renders).
    readonly property int fullHeight: header.height + banner.height + pageLoader.y + pageLoader.height + 4 * Theme.space
    color: Theme.window

    // The one table the navigation, the header and the page loader read.
    readonly property var pages: [
        { key: "firstrun", label: "Set up", subtitle: "Four steps, then play.", icon: Icons.sparkles, source: "FirstRunPage.qml" },
        { key: "game", label: "Game", subtitle: "Which window to read, and which part of it.", icon: Icons.gamepad, source: "GamePage.qml" },
        { key: "translation", label: "Translation", subtitle: "Languages, translator and keys.", icon: Icons.translate, source: "TranslationPage.qml" },
        { key: "appearance", label: "Appearance", subtitle: "How the subtitles look.", icon: Icons.palette, source: "AppearancePage.qml" },
        { key: "hotkeys", label: "Hotkeys", subtitle: "Global shortcuts; press the keys to set one.", icon: Icons.keyboard, source: "HotkeysPage.qml" },
        { key: "licence", label: "Licence", subtitle: "Trial, key and the data on this computer.", icon: Icons.key, source: "LicencePage.qml" },
        { key: "advanced", label: "Advanced", subtitle: "Timing, filters and diagnostics.", icon: Icons.sliders, source: "AdvancedPage.qml" },
    ]
    readonly property var current: pages.find(function(p) { return p.key === root.page }) || pages[0]

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
                id: header
                Layout.fillWidth: true
                title: root.current.label
                subtitle: root.current.subtitle
                status: backend.status
            }

            Banner {
                id: banner
                Layout.leftMargin: 4 * Theme.space
                Layout.topMargin: visible ? 2 * Theme.space : 0
                Layout.preferredWidth: pageLoader.width
                text: backend.problem
                onDismissed: backend.clearProblem()
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: pageLoader.height + 6 * Theme.space
                clip: true
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 6; color: Theme.borderStrong }
                }

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

    ProfilePopup { id: profiles }
}
