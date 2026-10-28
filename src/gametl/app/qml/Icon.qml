import QtQuick

// A stroke icon from inline SVG path data (24 x 24 viewBox, Lucide style),
// tinted with `color`. No image files, no shader effects: renders on the
// software backend too.
Item {
    id: root
    property string path: ""
    property color color: Theme.textSoft
    property real size: 18
    property real strokeWidth: 1.8

    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.fill: parent
        sourceSize: Qt.size(root.size * 2 * uiScale, root.size * 2 * uiScale)  // drawn at twice the screen's pixels: smooth edges
        smooth: true
        source: "data:image/svg+xml;utf8,"
            + "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='"
            + root.color.toString().replace("#", "%23")
            + "' stroke-width='" + root.strokeWidth + "' stroke-linecap='round' stroke-linejoin='round'>"
            + root.path + "</svg>"
    }
}
