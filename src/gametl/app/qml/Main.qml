import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The settings window's content: side navigation, header, the current page.
// `backend` (a SettingsBackend, set as a context property by the window)
// is what the pages read and write.
Rectangle {
    id: root
    property string page: "firstrun"
    // The height at which the current page shows whole (for full-page renders).
    readonly property int fullHeight: header.height + banner.height + pageLoader.y + pageLoader.height + 4 * Theme.space
    width: 1000
    height: 680
    color: Theme.window

    readonly property var titles: ({
        "firstrun": ["Set up", "Four steps, then play."],
        "game": ["Game", "Which window to read, and which part of it."],
        "translation": ["Translation", "Languages, translator and keys."],
        "appearance": ["Appearance", "How the subtitles look."],
        "hotkeys": ["Hotkeys", "Global shortcuts; press the keys to set one."],
        "licence": ["Licence", "Trial, key and the data on this computer."],
        "advanced": ["Advanced", "Timing, filters and diagnostics."]
    })
    readonly property var pages: ({
        "firstrun": firstRun, "game": game, "translation": translation, "appearance": appearance,
        "hotkeys": hotkeys, "licence": licence, "advanced": advanced
    })

    RowLayout {
        anchors.fill: parent
        spacing: 0

        SideNav {
            Layout.fillHeight: true
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
                title: root.titles[root.page][0]
                subtitle: root.titles[root.page][1]
                status: backend.status
            }

            Banner {
                id: banner
                Layout.fillWidth: true
                Layout.leftMargin: 4 * Theme.space
                Layout.rightMargin: 4 * Theme.space
                Layout.topMargin: visible ? 2 * Theme.space : 0
                Layout.preferredWidth: Math.min(Theme.contentWidth, parent.width - 8 * Theme.space)
                Layout.maximumWidth: Theme.contentWidth
                Layout.alignment: Qt.AlignLeft
                text: backend.problem
                onDismissed: backend.clearProblem()
            }

            Flickable {
                id: flick
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
                    sourceComponent: root.pages[root.page]
                }
            }
        }
    }

    Component { id: firstRun; FirstRunPage { width: pageLoader.width } }
    Component { id: game; GamePage { width: pageLoader.width } }
    Component { id: translation; TranslationPage { width: pageLoader.width } }
    Component { id: appearance; AppearancePage { width: pageLoader.width } }
    Component { id: hotkeys; HotkeysPage { width: pageLoader.width } }
    Component { id: licence; LicencePage { width: pageLoader.width } }
    Component { id: advanced; AdvancedPage { width: pageLoader.width } }

    ProfilePopup { id: profiles }
}
