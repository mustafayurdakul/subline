import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Card {
        title: "Languages"
        SettingRow {
            label: "OCR language"
            helper: "The script the game writes in: en, de, japan, korean, cyrillic..."
            Combo { map: root.s; key: "lang"; options: backend.ocrLangs; implicitWidth: 180 }
        }
        SettingRow {
            label: "Read on the GPU"
            helper: "DirectML, any DirectX 12 card. Faster for large areas, slower than the CPU on a subtitle strip."
            Toggle { map: root.s; key: "ocr_gpu" }
        }
        SettingRow {
            label: "Source language"
            helper: "What the translator is told the text is in."
            Field { map: root.s; key: "source_lang"; placeholderText: "same as OCR language"; implicitWidth: 180 }
        }
        SettingRow {
            label: "Target language"
            Field { map: root.s; key: "target_lang"; implicitWidth: 180 }
        }
    }

    Card {
        title: "Translator"
        SettingRow {
            label: "Service"
            helper: "DeepL and Claude need their key below. Offline runs on this computer."
            Segmented { map: root.s; key: "translator"; options: ["DeepL", "Claude", "Offline"]; values: ["deepl", "claude", "offline"] }
        }
        SettingRow {
            label: "Draft"
            helper: "A fast first version, replaced when the translator answers."
            Segmented { map: root.s; key: "draft"; options: ["None", "Offline", "DeepL"]; values: ["", "offline", "deepl"] }
        }
        SettingRow {
            label: "Offline model"
            helper: backend.downloadStatus !== "" ? backend.downloadStatus : "For the language pair above; about 100 MB, once."
            SecondaryButton { text: "Download"; icon_: Icons.download; enabled: !backend.downloading; onClicked: backend.downloadModel() }
        }
        SettingRow {
            label: "Remember translations on disk"
            helper: "Per game; a line seen before is never sent again."
            Toggle { map: root.s; key: "use_cache_file" }
        }
    }

    Card {
        title: "API keys"
        helper: "Kept in Windows Credential Manager, never in a profile. Save blanks the field."
        SettingRow {
            label: "DeepL key"
            helper: backend.deeplKeyStatus
            RowLayout {
                spacing: Theme.space
                Field { id: deeplField; placeholderText: "paste the key"; secret: true; implicitWidth: 240; onAccepted: deeplSave.clicked() }
                SecondaryButton { id: deeplSave; text: "Save"; onClicked: { backend.saveKey("DEEPL_AUTH_KEY", deeplField.text); deeplField.text = "" } }
                SecondaryButton { text: "Clear"; onClicked: { backend.clearKey("DEEPL_AUTH_KEY"); deeplField.text = "" } }
            }
        }
        SettingRow {
            label: "Anthropic key"
            helper: backend.anthropicKeyStatus
            RowLayout {
                spacing: Theme.space
                Field { id: anthropicField; placeholderText: "paste the key"; secret: true; implicitWidth: 240; onAccepted: anthropicSave.clicked() }
                SecondaryButton { id: anthropicSave; text: "Save"; onClicked: { backend.saveKey("ANTHROPIC_API_KEY", anthropicField.text); anthropicField.text = "" } }
                SecondaryButton { text: "Clear"; onClicked: { backend.clearKey("ANTHROPIC_API_KEY"); anthropicField.text = "" } }
            }
        }
    }

    Card {
        title: "Claude"
        SettingRow {
            label: "Model"
            Combo { map: root.s; key: "model"; options: backend.claudeModels; implicitWidth: 220 }
        }
        SettingRow {
            label: "Effort"
            Segmented { map: root.s; key: "effort"; options: ["Low", "Medium", "High"]; values: ["low", "medium", "high"] }
        }
        SettingRow {
            label: "Thinking"
            Segmented { map: root.s; key: "thinking"; options: ["Off", "Adaptive"]; values: ["disabled", "adaptive"] }
        }
        SettingRow {
            label: "Structured output"
            helper: "Server-side JSON: slower, never malformed."
            Toggle { map: root.s; key: "structured" }
        }
        SettingRow {
            label: "Glossary"
            helper: "A JSON file of term: translation pairs."
            RowLayout {
                spacing: Theme.space
                Field { map: root.s; key: "glossary_path"; placeholderText: "none"; implicitWidth: 220 }
                SecondaryButton { text: "Browse"; icon_: Icons.folder; onClicked: backend.browseGlossary() }
            }
        }
        SettingRow {
            label: "Tone notes"
            helper: "Formality, register, who speaks how."
            Field { map: root.s; key: "tone"; placeholderText: "optional"; implicitWidth: 300 }
        }
    }
}
