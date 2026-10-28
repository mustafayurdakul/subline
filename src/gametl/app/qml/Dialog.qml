import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The modal chrome shared by the app's popups: dimmed window, a card in
// the middle, a title; the body goes in `content`.
Popup {
    id: root
    property string title: ""
    default property alias content: body.data

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: 440
    padding: 3 * Theme.space
    background: Rectangle { radius: Theme.radius; color: Theme.card; border.color: Theme.borderStrong }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.3) }

    contentItem: ColumnLayout {
        id: body
        spacing: 2 * Theme.space
        Label { text: root.title; font.pixelSize: Theme.sizeTitle; font.weight: Font.DemiBold }
    }
}
