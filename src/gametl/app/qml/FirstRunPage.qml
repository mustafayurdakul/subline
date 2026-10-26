import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons
import "Format.js" as Format

// Four steps on one page: window, area, translator, start.
ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Card {
        step: 1
        title: "Which game?"
        helper: "Pick the game window. Start the game first, then Refresh."
        SettingRow { label: "Game window"; WindowPicker { fieldWidth: 300 } }
    }

    Card {
        step: 2
        title: "Where are the subtitles?"
        helper: "Most games draw them in the bottom quarter. Select on screen if yours differ: drag, nudge with the arrow keys, Enter."
        SettingRow {
            label: "Area to translate"
            helper: root.s.roi === "" ? "whole window" : root.s.roi
            AreaButtons {}
        }
    }

    Card {
        step: 3
        title: "Who translates?"
        helper: "DeepL is fast and free for 500k characters a month. Claude keeps names and tone consistent. Offline needs no key."
        SettingRow { label: "Translator"; TranslatorPicker {} }
        SettingRow { label: "Target language"; Field { key: "target_lang"; implicitWidth: 100 } }
        SettingRow {
            visible: root.s.translator === "deepl" || root.s.translator === "claude"
            label: root.s.translator === "deepl" ? "DeepL key" : "Anthropic key"
            helper: root.s.translator === "deepl" ? backend.deeplKeyStatus : backend.anthropicKeyStatus
            KeyEntry { name: root.s.translator === "deepl" ? "DEEPL_AUTH_KEY" : "ANTHROPIC_API_KEY"; fieldWidth: 300 }
        }
        ModelDownloadRow { visible: root.s.translator === "offline" }
    }

    Card {
        step: 4
        title: "Play"
        helper: "Press " + Format.hotkey(root.s.hotkey_toggle, "+") + " in the game at any time to start or stop. The pages on the left refine the rest."
        RowLayout {
            Layout.fillWidth: true
            spacing: 2 * Theme.space
            PrimaryButton { visible: backend.status === "idle"; text: "Start overlay"; icon_: Icons.play; onClicked: backend.start() }
            SecondaryButton { visible: backend.status !== "idle"; text: "Stop overlay"; icon_: Icons.stop; onClicked: backend.stop() }
            SecondaryButton { text: "Save as profile"; icon_: Icons.folder; onClicked: backend.saveProfile("") }
            Item { Layout.fillWidth: true }
            Caption { text: backend.licenseText; font.pixelSize: Theme.sizeCaption; elide: Text.ElideRight; wrapMode: Text.NoWrap; Layout.maximumWidth: 240 }
        }
    }
}
