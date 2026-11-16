$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
$appId = 'FabWatch.Desktop'
$manager = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.UI.Notifications.ToastNotifier, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.UI.Notifications.ToastNotificationHistory, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.UI.Notifications.NotificationSetting, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]
$notifier = $manager::CreateToastNotifier($appId)
$setting = $notifier.Setting
if ($null -ne $setting -and "$setting" -ne 'Enabled') { throw "Windows notification setting: $setting" }
$title = [Security.SecurityElement]::Escape([string]$inputData.title)
$body = [Security.SecurityElement]::Escape([string]$inputData.body)
$launch = ''
if ($inputData.url) {
    $url = [uri]$inputData.url
    if ($url.Scheme -ne 'https' -or $url.Host -notin @('www.fab.com','forums.unrealengine.com')) {
        throw 'Unexpected notification URL'
    }
    $safeUrl = [Security.SecurityElement]::Escape($url.AbsoluteUri)
    $launch = " activationType=`"protocol`" launch=`"$safeUrl`""
}
$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]::new()
$actions = ''
if ($inputData.snooze_url -and $inputData.read_url) {
    $snooze = [uri]$inputData.snooze_url
    $read = [uri]$inputData.read_url
    if ($snooze.Scheme -ne 'fabwatch' -or $snooze.Host -ne 'snooze' -or $read.Scheme -ne 'fabwatch' -or $read.Host -ne 'read') {
        throw 'Unexpected notification action'
    }
    $safeSnooze = [Security.SecurityElement]::Escape($snooze.AbsoluteUri)
    $safeRead = [Security.SecurityElement]::Escape($read.AbsoluteUri)
    $actions = "<actions><action content='Remind me later (30 min)' activationType='protocol' arguments='$safeSnooze'/><action content='Mark as read' activationType='protocol' arguments='$safeRead'/></actions>"
}
$iconPath = [Security.SecurityElement]::Escape(([uri](Join-Path $PSScriptRoot 'fab-watch.png')).AbsoluteUri)
$xml.LoadXml("<toast$launch><visual><binding template='ToastGeneric'><image placement='appLogoOverride' src='$iconPath'/><text>$title</text><text>$body</text></binding></visual>$actions</toast>")
$toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]::new($xml)
$toast.Tag = $inputData.tag
$toast.Group = 'FabMonitor'
$notifier.Show($toast)
for ($i = 0; $i -lt 10; $i++) {
    $history = $manager::History.GetHistory($appId)
    if ($history | Where-Object { $_.Tag -eq $toast.Tag -and $_.Group -eq $toast.Group }) {
        'accepted_by_os'
        exit 0
    }
    Start-Sleep -Milliseconds 250
}
throw 'Windows did not confirm the toast in Notification Center'
