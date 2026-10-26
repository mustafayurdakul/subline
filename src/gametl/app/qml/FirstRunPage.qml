import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Four steps on one page: window, area, translator, start.
ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Component.onCompleted: backend.refreshWindows()

    Card {
        step: 1
        title: "Which game?"
        helper: "Pick the game window. Start the game first, then Refresh."
        SettingRow {
            label: "Game window"
            RowLayout {
                spacing: Theme.space
                Combo { map: root.s; key: "window_match"; options: backend.windows; implicitWidth: 300 }
                SecondaryButton { text: "Refresh"; icon_: Icons.refresh; onClicked: backend.refreshWindows() }
            }
        }
    }

    Card {
        step: 2
        title: "Where are the subtitles?"
        helper: "Most games draw them in the bottom quarter. Select on screen if yours differ: drag, nudge with the arrow keys, Enter."
        SettingRow {
            label: "Area to translate"
            helper: root.s.roi === "" ? "whole window" : root.s.roi
            RowLayout {
                spacing: Theme.space
                SecondaryButton { text: "Bottom strip"; onClicked: backend.useBottomStrip() }
                SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair; onClicked: backend.selectArea() }
            }
        }
    }

    Card {
        step: 3
        title: "Who translates?"
        helper: "DeepL is fast and free for 500k characters a month. Claude keeps names and tone consistent. Offline needs no key."
        SettingRow {
            label: "Translator"
            Segmented { map: root.s; key: "translator"; options: ["DeepL", "Claude", "Offline"]; values: ["deepl", "claude", "offline"] }
        }
        SettingRow {
            label: "Target language"
            Field { map: root.s; key: "target_lang"; implicitWidth: 100 }
        }
        SettingRow {
            visible: root.s.translator === "deepl" || root.s.translator === "claude"
            label: root.s.translator === "deepl" ? "DeepL key" : "Anthropic key"
            helper: root.s.translator === "deepl" ? backend.deeplKeyStatus : backend.anthropicKeyStatus
            RowLayout {
                spacing: Theme.space
                Field { id: keyField; placeholderText: "paste the key"; secret: true; implicitWidth: 300; onAccepted: saveKey.clicked() }
                SecondaryButton {
                    id: saveKey
                    text: "Save"
                    onClicked: {
                        backend.saveKey(root.s.translator === "deepl" ? "DEEPL_AUTH_KEY" : "ANTHROPIC_API_KEY", keyField.text)
                        keyField.text = ""
                    }
                }
            }
        }
        SettingRow {
            visible: root.s.translator === "offline"
            label: "Offline model"
            helper: backend.downloadStatus !== "" ? backend.downloadStatus : "Downloaded once per language pair, about 100 MB."
            SecondaryButton { text: "Download"; icon_: Icons.download; enabled: !backend.downloading; onClicked: backend.downloadModel() }
        }
    }

    Card {
        step: 4
        title: "Play"
        helper: "Press " + hotkeyText(root.s.hotkey_toggle) + " in the game at any time to start or stop. The pages on the left refine the rest."
        function hotkeyText(combo) {
            return String(combo).split("+").map(function(p) { return p.charAt(0).toUpperCase() + p.slice(1) }).join("+")
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 2 * Theme.space
            PrimaryButton { visible: backend.status === "idle"; text: "Start overlay"; icon_: Icons.play; onClicked: backend.start() }
            SecondaryButton { visible: backend.status !== "idle"; text: "Stop overlay"; icon_: Icons.stop; onClicked: backend.stop() }
            SecondaryButton { text: "Save as profile"; icon_: Icons.folder; onClicked: backend.saveProfile("") }
            Item { Layout.fillWidth: true }
            Text { text: backend.licenseText; color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1; elide: Text.ElideRight; Layout.maximumWidth: 240 }
        }
    }
}
