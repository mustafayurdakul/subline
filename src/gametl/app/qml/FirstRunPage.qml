import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Four steps on one page: window, area, translator, start.
ColumnLayout {
    id: root
    property var backend
    spacing: 2 * Theme.space

    Card {
        step: 1
        title: "Which game?"
        helper: "Pick the game window. Start the game first, then Refresh."
        SettingRow {
            label: "Game window"
            RowLayout {
                spacing: Theme.space
                Field { text: backend.windowMatch; implicitWidth: 300 }
                SecondaryButton { text: "Refresh"; icon_: Icons.refresh }
            }
        }
    }

    Card {
        step: 2
        title: "Where are the subtitles?"
        helper: "Most games draw them in the bottom quarter. Select on screen if yours differ: drag, nudge with the arrow keys, Enter."
        SettingRow {
            label: "Area to translate"
            helper: backend.roi === "" ? "whole window" : backend.roi
            RowLayout {
                spacing: Theme.space
                SecondaryButton { text: "Bottom strip" }
                SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair }
            }
        }
    }

    Card {
        step: 3
        title: "Who translates?"
        helper: "DeepL is fast and free for 500k characters a month. Claude keeps names and tone consistent. Offline needs no key."
        SettingRow {
            label: "Translator"
            Segmented { options: ["DeepL", "Claude", "Offline"]; current: backend.translatorIndex }
        }
        SettingRow {
            label: "Target language"
            Field { text: backend.targetLang; implicitWidth: 100 }
        }
        SettingRow {
            label: "API key"
            helper: backend.keyStatus
            RowLayout {
                spacing: Theme.space
                Field { placeholderText: "paste the key"; secret: true; implicitWidth: 300 }
                SecondaryButton { text: "Save" }
            }
        }
    }

    Card {
        step: 4
        title: "Play"
        helper: "Press Ctrl+Shift+T in the game at any time to start or stop. The settings on the left refine the rest."
        RowLayout {
            Layout.fillWidth: true
            spacing: 2 * Theme.space
            PrimaryButton { text: "Start overlay"; icon_: Icons.play }
            SecondaryButton { text: "Save as profile"; icon_: Icons.folder }
            Item { Layout.fillWidth: true }
            Text { text: "Trial: 14 days left"; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1 }
        }
    }
}
