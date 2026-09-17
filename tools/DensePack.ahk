; DensePack hotkey.
;
; Highlight text in any application, press Ctrl+Shift+D, and the selection is
; replaced by a dense image of the same text.
;
; Windows gives no way to add an item to another application's text menu. Copy and
; Cut are drawn by each application itself. A hotkey reaches every application,
; which is the same result by a different key.
;
; Ctrl+Right-click   show the DensePack menu at the cursor, in any application
; Ctrl+Shift+D       pack the selection and paste the image over it
; Ctrl+Shift+C       pack the selection and leave the image on the clipboard,
;                    changing nothing
;
; Every route passes no size, so the packer draws the plugin's one page:
; 17 px unless DENSEPACK_CODE_PX names another number.

#Requires AutoHotkey v2.0
#SingleInstance Force

; The tray shows the DensePack icon from the repository's icon folder, since
; 12 September 2026. A missing file leaves AutoHotkey's own icon in place.
ICON := A_ScriptDir "\..\icon\DensePack.ico"
if FileExist(ICON)
    TraySetIcon(ICON)

TOOLS := A_ScriptDir
SCRIPT := TOOLS "\densepack-clip.ps1"

; The menu applications will not draw for us. Cut, Copy and Paste menus belong
; to each application, and Windows lets no outside program add to them. So
; DensePack draws its own menu at the cursor on Ctrl+Right-click, which works
; in every text box: editors, chat boxes, browsers.
DPMenu := Menu()
DPMenu.Add("DensePack it (replace selection)", (*) => Pack(true))
DPMenu.Add("DensePack to clipboard", (*) => Pack(false))

TrayTip("DensePack ready", "Ctrl+Right-click for the menu. Ctrl+Shift+D replaces, Ctrl+Shift+C packs to clipboard.")

Pack(replace) {
    global SCRIPT

    saved := ClipboardAll()
    A_Clipboard := ""
    Send("^c")
    if !ClipWait(2) {
        A_Clipboard := saved
        TrayTip("DensePack", "Nothing selected.")
        return
    }

    ; Pasting an image into a chat box lands as an attachment and leaves the
    ; selected text standing, so replace mode deletes the selection here. The
    ; copied text is still on the clipboard, and goes back with Ctrl+V if
    ; packing fails, so the text is never lost either way.
    if replace
        Send("{Delete}")

    code := RunWait('powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' SCRIPT '" -Quiet', , "Hide")
    if (code != 0) {
        if replace {
            Sleep(100)
            Send("^v")
        }
        TrayTip("DensePack", "Packing failed. The text was put back.")
        return
    }

    Sleep(150)
    if replace
        Send("^v")
    else
        TrayTip("DensePack", "Packed image is on the clipboard.")
}

^+d:: Pack(true)
^+c:: Pack(false)
^RButton:: DPMenu.Show()
