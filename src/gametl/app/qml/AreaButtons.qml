import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Ways to set the area to translate.
RowLayout {
    property bool wholeWindow: false  // also offer the whole window
    spacing: Theme.space
    SecondaryButton { text: "Bottom strip"; onClicked: backend.useBottomStrip() }
    SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair; onClicked: backend.selectArea() }
    SecondaryButton { visible: wholeWindow; text: "Whole window"; onClicked: backend.useWholeWindow() }
}
