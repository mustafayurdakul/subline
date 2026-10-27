import QtQuick
import QtQuick.Layouts

// A settings group: title, optional helper line, then its rows.
Rectangle {
    id: root
    property string title: ""
    property string helper: ""
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

        ColumnLayout {
            Layout.fillWidth: true
            visible: root.title !== ""
            spacing: 2
            Label { text: root.title; font.pixelSize: Theme.sizeTitle; font.weight: Font.DemiBold }
            Caption { visible: root.helper !== ""; text: root.helper; Layout.fillWidth: true }
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
