Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
pythonRun = fso.BuildPath(root, "python_app\run.py")
cmdLauncher = fso.BuildPath(root, "Launch Alpaca Paper Trader.cmd")
instancePath = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlpacaPaperTrader\instance.json"
edgeProfile = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlpacaPaperTrader\EdgeAppIconProfile"

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Function InstanceUrl()
    InstanceUrl = ""
    On Error Resume Next
    If Not fso.FileExists(instancePath) Then Exit Function

    Set file = fso.OpenTextFile(instancePath, 1, False)
    text = file.ReadAll
    file.Close

    Set regex = New RegExp
    regex.Pattern = """url""\s*:\s*""([^""]+)"""
    regex.IgnoreCase = True
    If regex.Test(text) Then
        Set matches = regex.Execute(text)
        InstanceUrl = matches(0).SubMatches(0)
    End If
    On Error GoTo 0
End Function

Function IsAlive(url)
    IsAlive = False
    If Len(url) = 0 Then Exit Function

    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 500, 500, 500, 500
    http.open "GET", url & "/api/state", False
    http.send
    If Err.Number = 0 And http.status >= 200 And http.status < 500 Then
        IsAlive = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function ActiveUrl()
    url = InstanceUrl()
    If IsAlive(url) Then
        ActiveUrl = url
    Else
        ActiveUrl = ""
        On Error Resume Next
        If fso.FileExists(instancePath) Then fso.DeleteFile instancePath, True
        On Error GoTo 0
    End If
End Function

Function EdgePath()
    candidates = Array( _
        shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe", _
        shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\Edge\Application\msedge.exe" _
    )
    EdgePath = ""
    For Each candidate In candidates
        If fso.FileExists(candidate) Then
            EdgePath = candidate
            Exit Function
        End If
    Next
End Function

Sub OpenApp(url)
    edge = EdgePath()
    If Len(edge) > 0 Then
        If Not fso.FolderExists(edgeProfile) Then
            fso.CreateFolder edgeProfile
        End If
        shell.Run Quote(edge) & " --user-data-dir=" & Quote(edgeProfile) & " --no-first-run --new-window --app=" & Quote(url) & " --window-size=1280,900 --window-position=80,60", 1, False
    Else
        shell.Run Quote(url), 1, False
    End If
End Sub

If fso.FileExists(pythonw) Then
    shell.CurrentDirectory = root
    shell.Run Quote(pythonw) & " " & Quote(pythonRun) & " --no-browser", 0, False

    For i = 1 To 60
        WScript.Sleep 500
        url = ActiveUrl()
        If Len(url) > 0 Then
            OpenApp url
            WScript.Quit
        End If
    Next

    shell.Popup "Alpaca Paper Trader did not start. Try Launch Alpaca Paper Trader.cmd to see the error.", 10, "Alpaca Paper Trader", 48
Else
    shell.Run Quote(cmdLauncher), 1, False
End If
