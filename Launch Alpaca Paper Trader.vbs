Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
pythonExe = fso.BuildPath(root, ".venv\Scripts\python.exe")
pythonRun = fso.BuildPath(root, "python_app\run.py")
cmdLauncher = fso.BuildPath(root, "Launch Alpaca Paper Trader.cmd")
sourceRoot = LCase(fso.GetAbsolutePathName(fso.BuildPath(root, "python_app")))
instancePath = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlpacaPaperTrader\instance.json"
edgeProfile = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlpacaPaperTrader\EdgeAppIconProfile"
staleWarningShown = False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Function JsonValue(text, name)
    JsonValue = ""
    On Error Resume Next
    Set regex = New RegExp
    regex.Pattern = """" & name & """\s*:\s*(?:""([^""]*)""|(true|false|null|-?\d+))"
    regex.IgnoreCase = True
    If regex.Test(text) Then
        Set matches = regex.Execute(text)
        If Len(matches(0).SubMatches(0)) > 0 Then
            JsonValue = matches(0).SubMatches(0)
        Else
            JsonValue = matches(0).SubMatches(1)
        End If
    End If
    On Error GoTo 0
End Function

Function NormalizeJsonPath(value)
    NormalizeJsonPath = LCase(Replace(value, "\\", "\"))
End Function

Function InstanceUrl()
    InstanceUrl = ""
    On Error Resume Next
    If Not fso.FileExists(instancePath) Then Exit Function

    Set file = fso.OpenTextFile(instancePath, 1, False)
    text = file.ReadAll
    file.Close

    InstanceUrl = JsonValue(text, "url")
    On Error GoTo 0
End Function

Function RuntimeHealth(url)
    RuntimeHealth = ""
    If Len(url) = 0 Then Exit Function

    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 500, 500, 500, 500
    http.open "GET", url & "/api/health", False
    http.send
    If Err.Number = 0 And http.status >= 200 And http.status < 500 Then
        RuntimeHealth = http.responseText
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function IsCurrentHealth(healthText)
    IsCurrentHealth = False
    If LCase(JsonValue(healthText, "current")) <> "true" Then Exit Function
    If NormalizeJsonPath(JsonValue(healthText, "source_path")) <> sourceRoot Then Exit Function
    IsCurrentHealth = True
End Function

Sub ShowRuntimeWarning(url, healthText)
    If staleWarningShown Then Exit Sub
    staleWarningShown = True

    pid = JsonValue(healthText, "pid")
    status = JsonValue(healthText, "status")
    sourcePath = NormalizeJsonPath(JsonValue(healthText, "source_path"))
    If Len(pid) = 0 Then pid = "unknown"
    If Len(status) = 0 Then status = "missing health"
    If Len(sourcePath) = 0 Then sourcePath = "unknown source path"

    message = "A stale Alpaca Paper Trader backend is responding and will not be reused." & vbCrLf & _
        "URL: " & url & vbCrLf & _
        "PID: " & pid & vbCrLf & _
        "Status: " & status & vbCrLf & _
        "Source: " & sourcePath & vbCrLf & vbCrLf & _
        "Close that backend process if the current app cannot bind the preferred port."
    shell.Popup message, 15, "Alpaca Paper Trader stale runtime", 48
End Sub

Function ActiveUrl()
    ActiveUrl = ""
    url = InstanceUrl()
    If Len(url) = 0 Then Exit Function

    healthText = RuntimeHealth(url)
    If Len(healthText) > 0 And IsCurrentHealth(healthText) Then
        ActiveUrl = url
    Else
        ShowRuntimeWarning url, healthText
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

If Not fso.FileExists(pythonRun) Then
    shell.Popup "Alpaca Paper Trader startup failed. Missing file: " & pythonRun, 15, "Alpaca Paper Trader", 16
    WScript.Quit 1
End If

If Not fso.FileExists(pythonw) And Not fso.FileExists(pythonExe) Then
    shell.Run Quote(cmdLauncher), 1, False
    WScript.Quit 1
End If

smokePython = pythonExe
If Not fso.FileExists(smokePython) Then smokePython = pythonw
smokeExit = shell.Run(Quote(smokePython) & " " & Quote(pythonRun) & " --smoke", 0, True)
If smokeExit <> 0 Then
    shell.Popup "Alpaca Paper Trader Python startup check failed. This usually means the virtualenv or dependencies are missing. Opening the command launcher for the detailed error.", 15, "Alpaca Paper Trader", 16
    shell.Run Quote(cmdLauncher), 1, False
    WScript.Quit smokeExit
End If

launcherPython = pythonw
If Not fso.FileExists(launcherPython) Then launcherPython = pythonExe

shell.CurrentDirectory = root
shell.Run Quote(launcherPython) & " " & Quote(pythonRun) & " --no-browser", 0, False

For i = 1 To 60
    WScript.Sleep 500
    url = ActiveUrl()
    If Len(url) > 0 Then
        OpenApp url
        WScript.Quit
    End If
Next

shell.Popup "Alpaca Paper Trader did not start. Try Launch Alpaca Paper Trader.cmd to see the error.", 10, "Alpaca Paper Trader", 48
