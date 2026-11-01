import QtQuick

// A game-like frame with the subtitle on it as the overlay would draw it:
// the image comes from the window's preview provider, painted by the same
// code as the overlay, and is asked for again on every edit. The frame
// stands for a 1080p game; the image is the bottom-strip area (in chat
// mode the whole frame, so the card above the strip shows), so sizes in it
// are to scale (preview.py). Always dark, like a game: no theme colours.
Rectangle {
    id: root
    readonly property bool chat: String(backend.settings.render) === "chat"

    implicitHeight: width * 9 / 16
    clip: true
    color: "#0A0C10"

    // A dusk scene: sky, a tree line, a lit window. Enough to judge contrast.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#3A2C2C" }
            GradientStop { position: 0.55; color: "#2E2733" }
            GradientStop { position: 1.0; color: "#0E0E11" }
        }
    }
    Rectangle { x: parent.width * 0.62; y: parent.height * 0.18; width: 110; height: 110; radius: 55; color: "#E3C98E"; opacity: 0.28 }
    Repeater {
        model: 9
        Rectangle {
            required property int index
            x: index * root.width / 8 - 20
            y: root.height * (0.5 + 0.08 * ((index * 7) % 3))
            width: root.width / 6
            height: root.height * 0.6
            radius: 40
            color: "#15131A"
        }
    }
    Rectangle { x: parent.width * 0.74; y: parent.height * 0.66; width: 22; height: 30; color: "#E8B45A"; opacity: 0.85 }

    // The area read: the bottom quarter, as the default bottom strip. Asked
    // for at the screen's scale, so the text stays sharp on a 150 % screen.
    Image {
        id: zone
        width: parent.width
        y: root.chat ? 0 : parent.height * 0.75
        height: root.chat ? parent.height : parent.height * 0.25
        sourceSize.width: Math.round(width * uiScale)
        sourceSize.height: Math.round(height * uiScale)
        cache: false
        source: "image://overlay/" + backend.previewStamp
    }

    Rectangle {
        // Out of the chat card's way: the tag moves left when the card takes the top-right corner.
        readonly property bool cardHere: root.chat && String(backend.settings.chat_corner) === "top-right"
        anchors.right: cardHere ? undefined : parent.right
        anchors.left: cardHere ? parent.left : undefined
        anchors.top: parent.top
        anchors.margins: 10
        width: previewTag.implicitWidth + 16
        height: 22
        radius: 4
        color: Qt.rgba(0, 0, 0, 0.45)
        Label { id: previewTag; anchors.centerIn: parent; text: "Live preview"; color: Theme.textOnDark; opacity: 0.85; font.pixelSize: Theme.sizeTiny }
    }
}
