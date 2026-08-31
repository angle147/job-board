# 创建 Windows 定时任务：每天 9:00 自动更新校招数据
# 右键 → 使用 PowerShell 运行，或管理员 PowerShell 中执行

$taskName = "HanaJobBoardUpdate"
$pythonPath = "D:\Python\python.exe"
$scriptPath = "D:\hanako\招聘求职\01-招聘数据与看板\job-board\daily_update.py"
$workDir = "D:\hanako\招聘求职\01-招聘数据与看板\job-board"

# 删除旧任务（如果存在）
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建新任务
$action = New-ScheduledTaskAction -Execute $pythonPath `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $workDir

$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 9:00AM),
    (New-ScheduledTaskTrigger -Daily -At 5:00PM)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "每天 9:00 和 17:00 更新国企编制岗位与济南线下招聘活动"

Write-Host "✅ 定时任务已创建: $taskName" -ForegroundColor Green
Write-Host "   执行时间: 每天 9:00、17:00" -ForegroundColor Yellow
Write-Host "   脚本: $scriptPath" -ForegroundColor Yellow
Write-Host ""
Write-Host "管理命令:" -ForegroundColor Cyan
Write-Host "   查看状态: Get-ScheduledTask -TaskName $taskName"
Write-Host "   手动运行: Start-ScheduledTask -TaskName $taskName"
Write-Host "   删除任务: Unregister-ScheduledTask -TaskName $taskName"
