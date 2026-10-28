import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// Ways to set the area to translate.
RowLayout {
    spacing: Theme.space
    SecondaryButton { text: "Bottom strip"; onClicked: backend.useBottomStrip() }
    SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair; onClicked: backend.selectArea() }
    SecondaryButton { text: "Whole window"; onClicked: backend.useWholeWindow() }
}
