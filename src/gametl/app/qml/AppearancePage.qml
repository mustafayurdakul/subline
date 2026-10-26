import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var backend
    spacing: 2 * Theme.space

    SubtitlePreview {
        id: preview
        Layout.fillWidth: true
        fontPx: fontSize.value === 0 ? 22 : fontSize.value
        bold: boldToggle.checked
        background: ["pill", "shadow", "none"][backgroundPick.current]
        pillOpacity: pillAlpha.value / 255
        position: ["bottom", "source", "center"][positionPick.current]
        textColor: ownColour.checked ? "#F2F2F2" : "#D9B86A"
    }

    Card {
        title: "Text"
        SettingRow {
            label: "Font size"
            helper: "Learned from the game's first lines and then held, or a fixed size."
            Stepper { id: fontSize; value: backend.subtitleFontPx; from: 0; to: 120; step: 2; suffix: " px"; specialText: "game's own" }
        }
        SettingRow {
            label: "Colour"
            helper: "The game's own subtitle colour, sampled, or one of yours."
            RowLayout {
                spacing: Theme.space
                Toggle { id: ownColour; checked: true }
                Text { text: "game's own"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1 }
                Rectangle { width: 28; height: 28; color: "#D9B86A"; border.color: Theme.borderStrong; opacity: ownColour.checked ? 0.35 : 1 }
            }
        }
        SettingRow { label: "Bold"; Toggle { id: boldToggle; checked: backend.subtitleBold } }
        SettingRow {
            label: "Font"
            Field { text: "Segoe UI"; implicitWidth: 200 }
        }
    }

    Card {
        title: "Background"
        SettingRow {
            label: "Style"
            helper: "A dark pill, a soft shadow like the game's own text, or bare outlined text."
            Segmented { id: backgroundPick; options: ["Pill", "Shadow", "None"]; current: backend.subtitleBackgroundIndex }
        }
        SettingRow {
            label: "Pill opacity"
            Gauge { id: pillAlpha; value: 230; from: 0; to: 255 }
        }
    }

    Card {
        title: "Placement"
        SettingRow {
            label: "Position"
            helper: "Bottom gives a steady baseline. Source follows where the game drew the line."
            Segmented { id: positionPick; options: ["Bottom", "Source", "Centre"]; current: 0 }
        }
        SettingRow {
            label: "Hide the original line"
            helper: "When the subtitle is drawn elsewhere, cover the game's own text."
            Toggle { checked: true }
        }
    }

    Card {
        title: "What counts as a subtitle"
        helper: "HUD prompts and objectives often share the area. Subtitles are centred and one size; the rest is left alone."
        SettingRow {
            label: "Only centred text"
            helper: "Tolerance as a share of the area's width."
            Gauge { value: 10; from: 0; to: 50; suffix: " %"; specialText: "off" }
        }
        SettingRow {
            label: "Only subtitle-sized text"
            helper: "How far a line's height may differ from the learned size."
            Gauge { value: 35; from: 0; to: 100; suffix: " %"; specialText: "off" }
        }
    }

    Card {
        title: "Mode"
        SettingRow {
            label: "Render"
            helper: "Subtitle: one style in the area. In place: each translation on its own box, in the game's colours."
            Segmented { options: ["Subtitle", "In place"]; current: 0 }
        }
    }
}
