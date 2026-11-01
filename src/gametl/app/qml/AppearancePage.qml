import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    readonly property string colour: String(root.s.subtitle_color)
    readonly property bool ownColour: colour === ""
    // Subtitle mode needs an area: with the whole window the pipeline draws in place, and the
    // subtitle settings below do nothing.
    readonly property bool subtitleMode: String(s.render) === "subtitle" && String(s.roi) !== ""
    spacing: 2 * Theme.space

    SubtitlePreview { Layout.fillWidth: true }

    Card {
        title: "Mode"
        SettingRow {
            label: "Render"
            helper: "Subtitle: one style in the area set on the Game page (with the whole window, translations go in place). In place: each translation on its own box, in the game's colours."
            Segmented { key: "render"; options: ["Subtitle", "In place"]; values: ["subtitle", "inplace"] }
        }
        SettingRow {
            visible: String(root.s.render) === "inplace"
            label: "In-place style"
            helper: "Auto patches the original out in its own colours, or uses a pill where the background is busy."
            Segmented { key: "style"; options: ["Auto", "Patch", "Pill", "Outline"]; values: ["auto", "patch", "pill", "outline"] }
        }
    }

    Card {
        title: "Text"
        SettingRow {
            visible: root.subtitleMode
            label: "Subtitle size"
            helper: "Learned from the game's first lines and then held, or a fixed size. The preview shows it as on a 1080p game."
            Stepper { key: "subtitle_font_px"; from: 0; to: 200; step: 2; suffix: " px"; specialText: "game's own" }
        }
        SettingRow {
            visible: root.subtitleMode
            label: "Colour"
            helper: "The game's own subtitle colour, sampled, or one of yours."
            RowLayout {
                spacing: Theme.space
                Toggle { checked: root.ownColour; onToggled: root.s.subtitle_color = checked ? "" : "#FFFFFF" }
                Label { text: "game's own"; color: Theme.textSoft; font.pixelSize: Theme.sizeCaption }
                Field { visible: !root.ownColour; live: false; key: "subtitle_color"; placeholderText: "#RRGGBB"; implicitWidth: 110 }
                // The colour as the overlay will draw it (white when the text does not parse).
                Rectangle {
                    visible: !root.ownColour
                    width: Theme.controlHeight; height: Theme.controlHeight
                    radius: Theme.radius
                    color: backend.colourHex(root.colour)
                    border.color: Theme.borderStrong
                }
            }
        }
        SettingRow {
            label: "Font"
            helper: "Any font installed on this computer."
            Combo { key: "font"; options: backend.fontFamilies; fontPreview: true; implicitWidth: 220 }
        }
        SettingRow {
            visible: root.subtitleMode
            label: "Weight"
            Segmented { key: "subtitle_weight"; options: ["Regular", "Medium", "Semibold", "Bold"]; values: ["regular", "medium", "semibold", "bold"] }
        }
    }

    Card {
        visible: root.subtitleMode
        title: "Background"
        SettingRow {
            label: "Style"
            helper: "A dark pill, a soft shadow like the game's own text, or bare outlined text."
            Segmented { key: "subtitle_background"; options: ["Pill", "Shadow", "None"]; values: ["pill", "shadow", "none"] }
        }
        SettingRow { visible: String(root.s.subtitle_background) === "pill"; label: "Pill opacity"; Gauge { key: "subtitle_pill_alpha"; factor: 100 / 255; suffix: "%" } }
    }

    Card {
        visible: root.subtitleMode
        title: "Placement"
        SettingRow {
            label: "Position"
            helper: "Bottom gives a steady baseline. Source follows where the game drew the line."
            Segmented { key: "subtitle_position"; options: ["Bottom", "Source", "Centre"]; values: ["bottom", "source", "center"] }
        }
        SettingRow {
            label: "Hide the original line"
            helper: "Cover the game's own line under the translation."
            Toggle { key: "subtitle_hide_source" }
        }
    }

    Card {
        visible: root.subtitleMode
        title: "What counts as a subtitle"
        helper: "HUD prompts and objectives often share the area. Subtitles are centred and one size; the rest is left alone."
        SettingRow {
            label: "Only centred text"
            helper: "Tolerance as a share of the area's width."
            Gauge { key: "subtitle_center_tolerance"; from: 0; to: 50; suffix: "%"; specialText: "off" }
        }
        SettingRow {
            label: "Only subtitle-sized text"
            helper: "How far a line's height may differ from the learned size."
            Gauge { key: "subtitle_size_tolerance"; from: 0; to: 100; suffix: "%"; specialText: "off" }
        }
    }
}
