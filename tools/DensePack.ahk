; DensePack hotkey.
;
; Select text in any application and press Ctrl+Shift+D. The hotkey replaces
; the selection with a packed image of the same text.
;
; Windows has no way to add an item to the text menu of another application.
; Each application makes its own Copy and Cut items. A hotkey works in all
; applications and gives the same result with a key.
;
;   Ctrl+Right-click   show the DensePack menu at the cursor, in any application
;   Ctrl+Shift+D       pack the selection and paste the image over it
;   Ctrl+Shift+C       pack the selection and leave the image on the clipboard,
;                      changing nothing
;
; No hotkey or menu item passes a size. The packer makes the plugin's one image
; at 17 px unless DENSEPACK_CODE_PX names another number.
;
; Each pack saves the text and all images in a new folder. The folder name is
; the first three words of the text. The hotkeys save under tools\ctrl-shift-vault.
; The menu saves under tools\ctrl-right_click-vault.

#Requires AutoHotkey v2.0
#SingleInstance Force

; The tray shows the DensePack icon from the repository's icon folder. A missing
; file leaves AutoHotkey's own icon in place.
ICON := A_ScriptDir "\..\icon\DensePack.ico"
if FileExist(ICON)
    TraySetIcon(ICON)

TOOLS := A_ScriptDir
SCRIPT := TOOLS "\densepack-clip.ps1"
KEY_VAULT := "ctrl-shift-vault"
MENU_VAULT := "ctrl-right_click-vault"

; The setting for the warning, and the list of images densepack-clip.ps1 writes
; after each pack. The two files are in %LOCALAPPDATA%\DensePack, not in the
; repository.
STATE := EnvGet("LOCALAPPDATA") "\DensePack"
INI := STATE "\tool.ini"
LAST := STATE "\last-pack.txt"
try DirCreate(STATE)

; The script makes the two vault folders at the first start. You can then find
; them.
for name in [KEY_VAULT, MENU_VAULT]
    try DirCreate(TOOLS "\" name)

; An application does not show items from another program in its text menu. Cut,
; Copy and Paste are part of each application. For that reason DensePack shows
; its own menu at the cursor on Ctrl+Right-click. The menu works in all text
; boxes, such as editors, chat boxes and browsers.
DPMenu := Menu()
DPMenu.Add("DensePack it (replace selection)", (*) => Pack(true, MENU_VAULT))
DPMenu.Add("DensePack to clipboard", (*) => Pack(false, MENU_VAULT))

TrayTip("DensePack ready", "Ctrl+Right-click for the menu. Ctrl+Shift+D replaces, Ctrl+Shift+C packs to clipboard.")

; Shows the warning before the first replace. Returns false when you
; choose Cancel. The check box saves the choice in tool.ini, and the warning
; does not show again.
ReplaceWarningOk() {
    global INI, TOOLS, KEY_VAULT, MENU_VAULT
    if (IniRead(INI, "warning", "replace_hidden", "0") = "1")
        return true
    target := WinExist("A")
    choice := {go: false, hide: 0}
    box := Gui("+AlwaysOnTop", "DensePack")
    box.SetFont("s10")
    box.AddText("w480",
        "Ctrl+Shift+D and the menu item DensePack it remove the selected text "
        . "and paste a DensePack image in its place.`n`n"
        . "DensePack saves the text and all images in a new folder here:`n"
        . TOOLS "\" KEY_VAULT "`n"
        . TOOLS "\" MENU_VAULT "`n`n"
        . "The text also stays in the Windows clipboard history (Win+V) when "
        . "clipboard history is on.")
    hide := box.AddCheckbox("", "Do not show this message again")
    go := box.AddButton("Default w110", "Continue")
    stop := box.AddButton("x+10 w110", "Cancel")
    go.OnEvent("Click", (*) => (choice.hide := hide.Value, choice.go := true, box.Destroy()))
    stop.OnEvent("Click", (*) => box.Destroy())
    box.OnEvent("Close", (*) => box.Destroy())
    box.OnEvent("Escape", (*) => box.Destroy())
    box.Show()
    WinWaitClose("ahk_id " box.Hwnd)
    if !choice.go
        return false
    if choice.hide
        try IniWrite("1", INI, "warning", "replace_hidden")
    ; The warning takes the focus. The function returns the focus to the window
    ; with the selection.
    if target {
        try WinActivate("ahk_id " target)
        WinWaitActive("ahk_id " target, , 1)
    }
    return true
}

; Runs densepack-clip.ps1 hidden and returns its exit code.
RunClip(arguments) {
    global SCRIPT
    return RunWait('powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' SCRIPT '" ' arguments, , "Hide")
}

Pack(replace, vault) {
    global LAST
    if replace && !ReplaceWarningOk()
        return
    saved := ClipboardAll()
    A_Clipboard := ""
    Send("^c")
    if !ClipWait(2) {
        A_Clipboard := saved
        TrayTip("DensePack", "Nothing selected.")
        return
    }

    ; A chat box adds a pasted image as an attachment and does not remove the
    ; selected text. For that reason replace mode deletes the selection here.
    ; The copied text is still on the clipboard. If the pack fails, Ctrl+V
    ; pastes the text again.
    if replace
        Send("{Delete}")

    try FileDelete(LAST)
    code := RunClip("-Quiet -Vault " vault)

    ; Line 1 of last-pack.txt is the folder. Each later line is one image.
    folder := ""
    images := []
    if (code = 0) && FileExist(LAST) {
        for line in StrSplit(FileRead(LAST, "UTF-8"), "`n", "`r") {
            if (line = "")
                continue
            if (folder = "")
                folder := line
            else
                images.Push(line)
        }
    }

    if (code != 0) || (images.Length = 0) {
        if replace {
            Sleep(100)
            Send("^v")
            TrayTip("DensePack", "DensePack made no image. It pasted the text again.")
        } else {
            TrayTip("DensePack", "DensePack made no image.")
        }
        return
    }

    Sleep(150)
    if !replace {
        if (images.Length = 1)
            TrayTip("DensePack", "The image is on the clipboard. The text and the image are in " folder)
        else
            TrayTip("DensePack", "The text needed " images.Length " images. Image 1 is on the clipboard. The text and all images are in " folder)
        return
    }

    ; Image 1 is on the clipboard. The loop puts each later image on the
    ; clipboard and pastes it, in order. A long text loses no part.
    Send("^v")
    Loop images.Length - 1 {
        Sleep(400)
        if (RunClip('-SetImage "' images[A_Index + 1] '"') != 0)
            break
        Sleep(150)
        Send("^v")
    }
    TrayTip("DensePack", "Pasted " images.Length (images.Length = 1 ? " image" : " images") ". The text and all images are in " folder)
}

^+d:: Pack(true, KEY_VAULT)
^+c:: Pack(false, KEY_VAULT)
^RButton:: DPMenu.Show()
