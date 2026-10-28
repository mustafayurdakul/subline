import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// The first page: one sentence, one button, the game, and the three
// settings a player touches. Everything else is on the pages to the left.
ColumnLayout {
    id: root
    readonly property bool idle: backend.status === "idle"
    spacing: 2 * Theme.space

    Item { Layout.preferredHeight: 2 * Theme.space }

    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: 12
        Label { text: "Translate game subtitles to"; font.pixelSize: Theme.sizeHero; font.weight: Font.DemiBold }
        Combo {
            key: "target_lang"
            options: backend.targetLanguageNames
            values: backend.targetLanguageCodes
            editable: false
            implicitWidth: 180
            implicitHeight: 44
            font.pixelSize: 20
            font.weight: Font.DemiBold
        }
    }
    Caption {
        Layout.alignment: Qt.AlignHCenter
        text: "Start any game. Its subtitles appear in your language, over the game, as they come."
        font.pixelSize: Theme.sizeCaption + 1
    }

    PrimaryButton {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 2 * Theme.space
        implicitWidth: 200
        implicitHeight: 52
        font.pixelSize: 18
        text: root.idle ? "Start" : backend.status === "starting" ? "Cancel" : "Stop"
        icon_: root.idle ? Icons.play : Icons.stop
        fill: root.idle ? Theme.accent : Theme.textSoft
        onClicked: root.idle ? backend.start() : backend.stop()
    }
    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: Theme.space
        Rectangle {
            width: 8; height: 8; radius: 4
            color: backend.status === "running" ? Theme.accent : Theme.borderStrong
        }
        Caption {
            font.pixelSize: Theme.sizeCaption
            text: backend.statusText !== "" ? backend.statusText
                : root.idle ? "Not running. Pick the game below and press Start." : "Starting…"
        }
    }

    Card {
        Layout.topMargin: 2 * Theme.space
        SettingRow { label: "Game"; helper: "The window to read. Part of its title is enough."; WindowPicker {} }
        SettingRow {
            label: "Subtitle size"
            helper: "Learned from the game, or set your own."
            Stepper { key: "subtitle_font_px"; from: 0; to: 200; step: 2; suffix: " px"; specialText: "game's own" }
        }
        SettingRow {
            label: "Background"
            helper: "A dark pill, a soft shadow, or bare text."
            Segmented { key: "subtitle_background"; options: ["Pill", "Shadow", "None"]; values: ["pill", "shadow", "none"] }
        }
        SettingRow {
            label: "Hide the original line"
            helper: "Cover the game's own text under the translation."
            Toggle { key: "subtitle_hide_source" }
        }
    }

    Caption { Layout.alignment: Qt.AlignHCenter; text: "Everything else is on the pages to the left." }
}
