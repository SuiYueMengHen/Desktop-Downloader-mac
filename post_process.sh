#!/bin/bash
# Post-processing for v1.0.0-alpha.3
# NOTE: QtDBus required by QtGui — do NOT remove.

APP="dist/Desktop Downloader.app"
FW="$APP/Contents/Frameworks"
RES="$APP/Contents/Resources"

echo "=== Post-processing ==="

# Remove unused Qt frameworks
for fw in QtPdf QtQml QtQmlMeta QtQmlModels QtQmlWorkerScript QtQuick QtVirtualKeyboard QtVirtualKeyboardQml; do
    rm -rf "$FW/PySide6/Qt/lib/${fw}.framework" 2>/dev/null
    rm -f "$FW/$fw" 2>/dev/null
    rm -f "$RES/$fw" 2>/dev/null
done
echo "  Removed unused Qt frameworks"

# Remove PIL libavif
rm -f "$FW/PIL/__dot__dylibs/libavif.16.3.0.dylib"
rm -f "$FW/PIL/_avif.cpython-313-darwin.so"
rm -f "$FW/libavif.16.3.0.dylib" 2>/dev/null
rm -f "$RES/libavif.16.3.0.dylib" 2>/dev/null
echo "  Removed PIL libavif"

# Remove PIL _imagingtk
rm -f "$FW/PIL/_imagingtk.cpython-313-darwin.so"
echo "  Removed PIL _imagingtk"

# Remove lxml isoschematron
rm -rf "$FW/lxml/isoschematron"
rm -rf "$RES/lxml/isoschematron"
echo "  Removed lxml isoschematron"

# Remove unused Qt plugins
rm -f "$FW/PySide6/Qt/plugins/platforminputcontexts/"*
rm -f "$FW/PySide6/Qt/plugins/networkinformation/"*
rm -f "$FW/PySide6/Qt/plugins/generic/"*
echo "  Removed unused Qt plugins"

# Re-sign
codesign --deep --force --sign - "$APP" 2>/dev/null
echo "  Re-signed"
du -sh "$APP"
echo "=== Done ==="
