import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The settings window's content: side navigation, header, the current page.
// `backend` is the object the pages read and write; until the Python side
// provides it, `mock` stands in with an Alan Wake 2 profile.
Rectangle {
    id: root
    property string page: "firstrun"
    property var backend: mock
    // The height at which the current page shows whole (for full-page renders).
    readonly property int fullHeight: header.height + pageLoader.y + pageLoader.height + 4 * Theme.space
    width: 1000
    height: 680
    color: Theme.window

    QtObject {
        id: mock
        property string windowMatch: "Alan Wake 2"
        property string game: "Alan Wake 2"
        property string roi: "0.0000,0.7500,1.0000,0.2500"
        property bool centerZone: false
        property int translatorIndex: 0
        property string targetLang: "tr"
        property string keyStatus: "DeepL key set (Windows Credential Manager)"
        property int subtitleFontPx: 0
        property bool subtitleBold: false
        property int subtitleBackgroundIndex: 0  // pill | shadow | none
        property string status: "running"
        property string statusText: "Running on Alan Wake 2 · DeepL · en → tr"
    }

    readonly property var titles: ({
        "firstrun": ["Set up", "Four steps, then play."],
        "game": ["Game", "Which window to read, and which part of it."],
        "translation": ["Translation", "Languages, translator and keys."],
        "appearance": ["Appearance", "How the subtitles look."],
        "hotkeys": ["Hotkeys", "Global shortcuts; press the keys to set one."],
        "licence": ["Licence", "Trial, key and the data on this computer."],
        "advanced": ["Advanced", "Timing, filters and debugging."]
    })

    RowLayout {
        anchors.fill: parent
        spacing: 0

        SideNav {
            Layout.fillHeight: true
            current: root.page
            onNavigate: function(key) { root.page = key }
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
                statusText: backend.statusText
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: pageLoader.height + 6 * Theme.space
                clip: true

                Loader {
                    id: pageLoader
                    x: 4 * Theme.space
                    y: 3 * Theme.space
                    width: Math.min(Theme.contentWidth, parent.width - 8 * Theme.space)
                    sourceComponent: root.page === "firstrun" ? firstRun
                                   : root.page === "game" ? game
                                   : root.page === "appearance" ? appearance : placeholder
                    onLoaded: item.backend = root.backend
                }
            }
        }
    }

    Component { id: firstRun; FirstRunPage { width: pageLoader.width } }
    Component { id: game; GamePage { width: pageLoader.width } }
    Component { id: appearance; AppearancePage { width: pageLoader.width } }
    Component {
        id: placeholder
        Item {
            property var backend
            width: pageLoader.width
            height: 80
            Text { text: "This page comes with the wiring step."; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.size }
        }
    }
}
