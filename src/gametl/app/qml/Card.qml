import QtQuick
import QtQuick.Layouts

// A settings group: title, optional helper line, then its rows.
Rectangle {
    id: root
    property string title: ""
    property string helper: ""
    property int step: 0  // 1..n shows a numbered badge (first-run flow)
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

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space + 2
            visible: root.title !== ""

            Rectangle {
                visible: root.step > 0
                width: 24; height: 24; radius: 12
                color: Theme.accentSoft
                border.color: Theme.accent
                Text {
                    anchors.centerIn: parent
                    text: root.step
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: Theme.sizeSmall
                    font.weight: Font.DemiBold
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: root.title
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
