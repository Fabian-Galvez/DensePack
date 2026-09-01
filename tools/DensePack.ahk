; DensePack hotkey.
;
; Highlight text in any application, press Ctrl+Shift+D, and the selection is
; replaced by a dense image of the same text.
;
; Windows gives no way to add an item to another application's text menu. Copy and
; Cut are drawn by each application itself. A hotkey reaches every application,
; which is the same result by a different key.
;
; Ctrl+Right-click   show the DensePack menu at the cursor, in any application.
;                    Each entry opens a side menu holding 8 px, 10 px and 12 px
; Ctrl+Shift+D       pack the selection at 10 px and paste the image over it
; Ctrl+Shift+C       pack the selection at 10 px and leave it on the clipboard,
;                    changing nothing
;
; The hotkeys pack at 10 px, the size Opus 5 and Fable 5 both read exactly. Use
; the Ctrl+Right-click menu to pick 8 px, which Fable 5 alone reads exactly, or
; 12 px, the size Sonnet 5 reads exactly.

#Requires AutoHotkey v2.0
#SingleInstance Force

TOOLS := A_ScriptDir
SCRIPT := TOOLS "\densepack-clip.ps1"

; The menu applications will not draw for us. Cut, Copy and Paste menus belong
; to each application, and Windows lets no outside program add to them. So
; DensePack draws its own menu at the cursor on Ctrl+Right-click, which works
; in every text box: editors, chat boxes, browsers.
; Each entry opens a side menu holding the three measured reading sizes, the
; same shape and the same order the Explorer entry uses. 8 px is read exactly
; by Fable 5 alone and draws the smallest image. 10 px is read exactly by
; Opus 5 and by Fable 5. 12 px is read exactly by Sonnet 5, and the other two
; read it more easily than the sizes they were scored at.
DPReplace := Menu()
DPReplace.Add("Fable 5, 8 px, smallest image", (*) => Pack(true, 8))
DPReplace.Add("Opus 5, 10 px, read by Opus 5 and Fable 5", (*) => Pack(true, 10))
DPReplace.Add("Sonnet 5, 12 px, read by all three", (*) => Pack(true, 12))

DPClip := Menu()
DPClip.Add("Fable 5, 8 px, smallest image", (*) => Pack(false, 8))
DPClip.Add("Opus 5, 10 px, read by Opus 5 and Fable 5", (*) => Pack(false, 10))
DPClip.Add("Sonnet 5, 12 px, read by all three", (*) => Pack(false, 12))

DPMenu := Menu()
DPMenu.Add("DensePack it (replace selection)", DPReplace)
DPMenu.Add("DensePack to clipboard", DPClip)

TrayTip("DensePack ready", "Ctrl+Right-click for the menu and a size. Ctrl+Shift+D replaces, Ctrl+Shift+C packs to clipboard, both at 10 px.")

Pack(replace, size := 10) {
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

    code := RunWait('powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' SCRIPT '" -Size ' size ' -Quiet', , "Hide")
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
