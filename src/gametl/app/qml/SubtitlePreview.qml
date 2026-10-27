import QtQuick

// A game-like frame with the subtitle on it as the overlay would draw it:
// the image comes from the window's preview provider, painted by the same
// code as the overlay, and is asked for again on every edit.
Rectangle {
    id: root

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

    // The subtitle zone: the bottom third, as a bottom-strip area would be.
    Image {
        id: zone
        x: 24
        width: parent.width - 48
        y: parent.height * 0.64
        height: parent.height * 0.36
        sourceSize.width: width
        sourceSize.height: height
        cache: false
        source: "image://overlay/" + backend.previewStamp
    }

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        width: previewTag.implicitWidth + 16
        height: 22
        color: Qt.rgba(0, 0, 0, 0.45)
        Label { id: previewTag; anchors.centerIn: parent; text: "Live preview"; color: Theme.textSoft; font.pixelSize: Theme.sizeTiny }
    }
}
