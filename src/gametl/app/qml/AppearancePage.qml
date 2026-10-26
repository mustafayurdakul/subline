import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    readonly property string colour: String(root.s.subtitle_color)
    readonly property bool ownColour: colour === ""
    readonly property string swatch: /^#[0-9a-fA-F]{6}$/.test(colour) ? colour : "#D9B86A"
    spacing: 2 * Theme.space

    SubtitlePreview {
        Layout.fillWidth: true
        fontPx: Number(root.s.subtitle_font_px) || 22
        bold: Boolean(root.s.subtitle_bold)
        background: String(root.s.subtitle_background)
        pillOpacity: Number(root.s.subtitle_pill_alpha) / 255
        position: String(root.s.subtitle_position)
        textColor: root.ownColour ? "#F2F2F2" : root.swatch
    }

    Card {
        title: "Text"
        SettingRow {
            label: "Font size"
            helper: "Learned from the game's first lines and then held, or a fixed size."
            Stepper { key: "subtitle_font_px"; from: 0; to: 200; step: 2; suffix: " px"; specialText: "game's own" }
        }
        SettingRow {
            label: "Colour"
            helper: "The game's own subtitle colour, sampled, or one of yours."
            RowLayout {
                spacing: Theme.space
                Toggle { checked: root.ownColour; onToggled: root.s.subtitle_color = checked ? "" : "#FFFFFF" }
                Label { text: "game's own"; color: Theme.textSoft; font.pixelSize: Theme.sizeCaption }
                Field { visible: !root.ownColour; key: "subtitle_color"; placeholderText: "#RRGGBB"; implicitWidth: 110 }
                Rectangle { width: 28; height: 28; color: root.swatch; border.color: Theme.borderStrong; opacity: root.ownColour ? 0.35 : 1 }
            }
        }
        SettingRow { label: "Bold"; Toggle { key: "subtitle_bold" } }
        SettingRow { label: "Font"; Field { key: "font"; implicitWidth: 200 } }
    }

    Card {
        title: "Background"
        SettingRow {
            label: "Style"
            helper: "A dark pill, a soft shadow like the game's own text, or bare outlined text."
            Segmented { key: "subtitle_background"; options: ["Pill", "Shadow", "None"]; values: ["pill", "shadow", "none"] }
        }
        SettingRow { label: "Pill opacity"; Gauge { key: "subtitle_pill_alpha"; from: 0; to: 255 } }
    }

    Card {
        title: "Placement"
        SettingRow {
            label: "Position"
            helper: "Bottom gives a steady baseline. Source follows where the game drew the line."
            Segmented { key: "subtitle_position"; options: ["Bottom", "Source", "Centre"]; values: ["bottom", "source", "center"] }
        }
        SettingRow {
            label: "Hide the original line"
            helper: "When the subtitle is drawn elsewhere, cover the game's own text."
            Toggle { key: "subtitle_hide_source" }
        }
    }

    Card {
        title: "What counts as a subtitle"
        helper: "HUD prompts and objectives often share the area. Subtitles are centred and one size; the rest is left alone."
        SettingRow {
            label: "Only centred text"
            helper: "Tolerance as a share of the area's width."
            Gauge { key: "subtitle_center_tolerance"; from: 0; to: 50; suffix: " %"; specialText: "off" }
        }
        SettingRow {
            label: "Only subtitle-sized text"
            helper: "How far a line's height may differ from the learned size."
            Gauge { key: "subtitle_size_tolerance"; from: 0; to: 100; suffix: " %"; specialText: "off" }
        }
    }

    Card {
        title: "Mode"
        SettingRow {
            label: "Render"
            helper: "Subtitle: one style in the area. In place: each translation on its own box, in the game's colours."
            Segmented { key: "render"; options: ["Subtitle", "In place"]; values: ["subtitle", "inplace"] }
        }
        SettingRow {
            visible: String(root.s.render) === "inplace"
            label: "In-place style"
            helper: "Auto patches the original out in its own colours, or uses a pill where the background is busy."
            Segmented { key: "style"; options: ["Auto", "Patch", "Pill", "Outline"]; values: ["auto", "patch", "pill", "outline"] }
        }
    }
}
