import QtQuick
import QtQuick.Controls.Basic as C
import QtQuick.Layouts

// The modal chrome shared by the app's popups: dimmed window, a card in
// the middle, a title; the body goes in `content`. (Controls is imported
// under a name: its own Dialog and Label would otherwise shadow the app's.)
C.Popup {
    id: root
    property string title: ""
    default property alias content: body.data

    modal: true
    focus: true
    closePolicy: C.Popup.CloseOnEscape
    anchors.centerIn: C.Overlay.overlay
    width: 440
    padding: 3 * Theme.space
    // A popup is drawn above the scaled page, so it takes the screen's scale itself,
    // growing from its corner: the centring already counts the scaled size.
    scale: uiScale
    transformOrigin: C.Popup.TopLeft
    background: Rectangle { radius: Theme.radius; color: Theme.card; border.color: Theme.borderStrong }
    C.Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.3) }

    contentItem: ColumnLayout {
        id: body
        spacing: 2 * Theme.space
        Label { text: root.title; font.pixelSize: Theme.sizeTitle; font.weight: Font.DemiBold }
    }
}
