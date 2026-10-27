import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    spacing: 2 * Theme.space

    Card {
        title: "Languages"
        SettingRow {
            label: "OCR language"
            helper: "The script the game writes in: en, de, japan, korean, cyrillic..."
            Combo { key: "lang"; options: backend.ocrLangs; implicitWidth: 180 }
        }
        SettingRow {
            label: "Read on the GPU"
            helper: "DirectML, any DirectX 12 card. Faster for large areas, slower than the CPU on a subtitle strip."
            Toggle { key: "ocr_gpu" }
        }
        SettingRow {
            label: "Source language"
            helper: "What the translator is told the text is in; empty follows the OCR language."
            Field { key: "source_lang"; placeholderText: "same as OCR language"; implicitWidth: 180 }
        }
        SettingRow { label: "Target language"; Field { key: "target_lang"; implicitWidth: 180 } }
    }

    Card {
        title: "Translator"
        SettingRow {
            label: "Service"
            helper: "DeepL and Claude need their key below. Offline runs on this computer, after a download."
            TranslatorPicker {}
        }
        SettingRow {
            label: "Draft"
            helper: "A fast first version, replaced when the translator answers."
            Segmented { key: "draft"; options: ["None", "Offline", "DeepL"]; values: ["", "offline", "deepl"] }
        }
        ModelDownloadRow {}
        SettingRow {
            label: "Remember translations on disk"
            helper: "Per game; a line seen before is never sent again."
            Toggle { key: "use_cache_file" }
        }
    }

    Card {
        title: "API keys"
        helper: "Kept in Windows Credential Manager, never in a profile. Save blanks the field."
        SettingRow { label: "DeepL key"; helper: backend.deeplKeyStatus; KeyEntry { name: "DEEPL_AUTH_KEY"; clearable: true } }
        SettingRow { label: "Anthropic key"; helper: backend.anthropicKeyStatus; KeyEntry { name: "ANTHROPIC_API_KEY"; clearable: true } }
    }

    Card {
        title: "Claude"
        SettingRow { label: "Model"; Combo { key: "model"; options: backend.claudeModels; implicitWidth: 220 } }
        SettingRow {
            label: "Effort"
            Segmented { key: "effort"; options: ["Low", "Medium", "High"]; values: ["low", "medium", "high"] }
        }
        SettingRow {
            label: "Thinking"
            Segmented { key: "thinking"; options: ["Off", "Adaptive"]; values: ["disabled", "adaptive"] }
        }
        SettingRow {
            label: "Structured output"
            helper: "Server-side JSON: slower, never malformed."
            Toggle { key: "structured" }
        }
        SettingRow {
            label: "Glossary"
            helper: "A JSON file of term: translation pairs."
            RowLayout {
                spacing: Theme.space
                Field { key: "glossary_path"; placeholderText: "none"; implicitWidth: 220 }
                SecondaryButton { text: "Browse"; icon_: Icons.folder; onClicked: backend.browseGlossary() }
            }
        }
        SettingRow {
            label: "Tone notes"
            helper: "Formality, register, who speaks how."
            Field { key: "tone"; placeholderText: "optional"; implicitWidth: 300 }
        }
    }
}
