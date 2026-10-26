import QtQuick

// A game-like frame with the subtitle drawn as the overlay would draw it:
// pill, soft shadow or bare outline, the chosen size, colour and weight.
// Shadows are offset copies of the text, as in the overlay itself, so the
// preview renders without shader effects.
Rectangle {
    id: root
    property string line: "Nereye gidiyorsun? Işıklar söndüğünde buradaydın."
    property int fontPx: 22
    property color textColor: "#F2F2F2"
    property bool bold: false
    property string background: "pill"  // "pill" | "shadow" | "none"
    property real pillOpacity: 230 / 255
    property string position: "bottom"

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

    Item {
        id: zone
        x: 24
        width: parent.width - 48
        y: parent.height * 0.70
        height: parent.height * 0.30

        Item {
            id: subtitle
            width: label.implicitWidth
            height: label.implicitHeight
            x: (zone.width - width) / 2
            y: root.position === "bottom" ? zone.height - height - 14
             : root.position === "center" ? (zone.height - height) / 2 : 10

            Rectangle {
                visible: root.background === "pill"
                anchors.fill: parent
                anchors.margins: -root.fontPx / 2
                anchors.topMargin: -root.fontPx / 5
                anchors.bottomMargin: -root.fontPx / 5
                radius: 8
                color: Qt.rgba(0, 0, 0, root.pillOpacity)
            }
            Repeater {
                model: root.background === "shadow" ? [[1, 1, 0.65], [2, 2, 0.45], [3, 3, 0.25], [0, 2, 0.25], [2, 0, 0.25]]
                     : root.background === "none" ? [[-1, -1, 0.85], [1, -1, 0.85], [-1, 1, 0.85], [1, 1, 0.85], [0, -1, 0.85], [0, 1, 0.85], [-1, 0, 0.85], [1, 0, 0.85]]
                     : []
                Text {
                    required property var modelData
                    x: modelData[0]; y: modelData[1]
                    text: root.line
                    color: Qt.rgba(0, 0, 0, modelData[2])
                    font.family: Theme.font
                    font.pixelSize: root.fontPx
                    font.bold: root.bold
                }
            }
            Text {
                id: label
                text: root.line
                color: root.textColor
                font.family: Theme.font
                font.pixelSize: root.fontPx
                font.bold: root.bold
            }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        width: previewTag.implicitWidth + 16
        height: 22
        color: Qt.rgba(0, 0, 0, 0.45)
        Text { id: previewTag; anchors.centerIn: parent; text: "Live preview"; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: 11 }
    }
}
