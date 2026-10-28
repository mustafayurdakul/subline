import QtQuick

// The three translators a player picks from; the test translators are picked by name on the Advanced page.
Segmented { key: "translator"; options: ["DeepL", "Claude", "Offline"]; values: ["deepl", "claude", "offline"] }
