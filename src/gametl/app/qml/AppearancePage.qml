import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    readonly property string colour: String(root.s.subtitle_color)
    readonly property bool ownColour: colour === ""
    readonly property bool chat: String(root.s.render) === "chat"
    spacing: 2 * Theme.space

    SubtitlePreview { Layout.fillWidth: true }

    Card {
        title: "Mode"
        SettingRow {
            label: "Render"
            helper: "Subtitle: one style in the area. Chat: the last lines as a transcript, with who said them; best with Claude, which translates each line in the light of the conversation. In place: each translation on its own box, in the game's colours."
            Segmented { key: "render"; options: ["Subtitle", "Chat", "In place"]; values: ["subtitle", "chat", "inplace"] }
        }
        SettingRow {
            visible: root.chat
            label: "Lines kept"
            helper: "How much of the conversation the card shows."
            Stepper { key: "chat_lines"; from: 1; to: 8 }
        }
        SettingRow {
            visible: root.chat
            label: "Clear after"
            helper: "A line leaves the card this long after it was last on screen, so the screen is clear between conversations."
            Stepper { key: "chat_seconds"; from: 0; to: 120; step: 5; suffix: " s"; specialText: "never" }
        }
        SettingRow {
            visible: root.chat
            label: "Corner"
            helper: "A bottom corner sits above the area read when that is the lower part of the window, clear of the game's own subtitles."
            Segmented { key: "chat_corner"; options: ["Bottom left", "Bottom right", "Top left", "Top right"]; values: ["bottom-left", "bottom-right", "top-left", "top-right"] }
        }
        SettingRow {
            visible: root.chat
            label: "Card width"
            helper: "As a share of the game window."
            Gauge { key: "chat_width"; from: 20; to: 70; stepSize: 2; suffix: "%" }
        }
        SettingRow {
            visible: root.chat
            label: "Time stamps"
            helper: "The clock time each line was said, in front of it."
            Toggle { key: "chat_timestamps" }
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
            label: "Font size"
            helper: "Learned from the game's first lines and then held, or a fixed size. The preview shows it as on a 1080p game."
            Stepper { key: "subtitle_font_px"; from: 0; to: 200; step: 2; suffix: " px"; specialText: "game's own" }
        }
        SettingRow {
            label: "Colour"
            helper: root.chat ? "White on the card, or one of yours." : "The game's own subtitle colour, sampled, or one of yours."
            RowLayout {
                spacing: Theme.space
                Toggle { checked: root.ownColour; onToggled: root.s.subtitle_color = checked ? "" : "#FFFFFF" }
                Label { text: root.chat ? "white" : "game's own"; color: Theme.textSoft; font.pixelSize: Theme.sizeCaption }
                Field { visible: !root.ownColour; key: "subtitle_color"; placeholderText: "#RRGGBB"; implicitWidth: 110 }
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
            label: "Weight"
            Segmented { key: "subtitle_weight"; options: ["Regular", "Medium", "SemiBold", "Bold"]; values: ["regular", "medium", "semibold", "bold"] }
        }
    }

    Card {
        title: "Background"
        SettingRow {
            visible: !root.chat
            label: "Style"
            helper: "A dark pill, a soft shadow like the game's own text, or bare outlined text."
            Segmented { key: "subtitle_background"; options: ["Pill", "Shadow", "None"]; values: ["pill", "shadow", "none"] }
        }
        SettingRow { label: root.chat ? "Card opacity" : "Pill opacity"; Gauge { key: "subtitle_pill_alpha"; factor: 100 / 255; suffix: "%" } }
    }

    Card {
        title: "Placement"
        SettingRow {
            visible: !root.chat
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
            Gauge { key: "subtitle_center_tolerance"; from: 0; to: 50; suffix: "%"; specialText: "off" }
        }
        SettingRow {
            label: "Only subtitle-sized text"
            helper: "How far a line's height may differ from the learned size."
            Gauge { key: "subtitle_size_tolerance"; from: 0; to: 100; suffix: "%"; specialText: "off" }
        }
    }

}
