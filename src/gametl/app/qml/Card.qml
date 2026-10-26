import QtQuick
import QtQuick.Layouts

// A settings group: title, optional helper line, then its rows.
Rectangle {
    id: root
    property string title: ""
    property string helper: ""
    property int step: 0  // 1..n numbers the card (first-run flow)
    property string stepStyle: "badge"
    default property alias content: body.data

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + 2 * padding
    radius: Theme.radius
    color: Theme.card
    border.color: Theme.border
    border.width: 1

    readonly property int padding: 2 * Theme.space

    ColumnLayout {
        id: column
        x: root.padding
        y: root.padding
        width: root.width - 2 * root.padding
        spacing: Theme.space

        // Title block. `stepStyle` picks how a step number shows:
        // "eyebrow"  small "STEP 1" line above the title
        // "inline"   the number leads the title, in the accent
        // "corner"   a large faint number at the card's right
        // "badge"    a small boxed number on the title line
        Item {
            Layout.fillWidth: true
            visible: root.title !== ""
            implicitHeight: titles.implicitHeight

            Rectangle {
                id: badge
                visible: root.step > 0 && root.stepStyle === "badge"
                width: 24; height: 24
                y: titleText.y + (titleText.height - height) / 2
                color: Theme.accentSoft
                border.color: Theme.accentDeep
                Text {
                    anchors.centerIn: parent
                    text: root.step
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: Theme.sizeSmall
                    font.weight: Font.DemiBold
                }
            }
            Text {
                visible: root.step > 0 && root.stepStyle === "corner"
                anchors.right: parent.right
                anchors.rightMargin: 2
                y: -6
                text: root.step < 10 ? "0" + root.step : root.step
                color: Theme.accent
                opacity: 0.45
                font.family: Theme.font
                font.pixelSize: 30
                font.weight: Font.Light
            }
            ColumnLayout {
                id: titles
                x: badge.visible ? badge.width + Theme.space + 2 : 0
                width: parent.width - x
                spacing: 2
                Text {
                    visible: root.step > 0 && root.stepStyle === "eyebrow"
                    text: "STEP " + root.step
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.2
                    Layout.bottomMargin: 2
                }
                Text {
                    id: titleText
                    text: root.step > 0 && root.stepStyle === "inline" ? root.step + ".  " + root.title : root.title
                    color: Theme.text
                    font.family: Theme.font
                    font.pixelSize: Theme.sizeTitle
                    font.weight: Font.DemiBold
                }
                Text {
                    visible: root.helper !== ""
                    text: root.helper
                    color: Theme.muted
                    font.family: Theme.font
                    font.pixelSize: Theme.sizeSmall
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            visible: root.title !== ""
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: Theme.space
        }
    }
}
