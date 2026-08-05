#!/usr/bin/env pwsh
# run_supervisor.ps1 — launcher Hermes FX AI Supervisor (Windows scheduled task).
# Запускает supervisor.py в цикле (decision_interval_min из config.yaml).
#
# Установка как scheduled task (AtLogon + repeating):
#   schtasks /Create /TN "HermesFX_Supervisor" /SC ONLOGON /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"<this script>`"" /RL HIGHEST
# Или через cron-эквивалент Claude (CronCreate durable) если Claude Code всегда открыт.
#
# ⚠ Терминал Hermes FX deploy должен быть запущен (mt5.initialize подключается к нему).
# ⚠ НЕ запускать против <TERMINAL_ID_XAU> (live XAU trader) — config.bridge.mt5_data_path = null
#   означает default запущенный терминал; убедись что это Hermes FX терминал, не XAU.

param(
    [string]$Config = "$PSScriptRoot\config.yaml",
    [switch]$DryRun,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pyArgs = @("-3", "supervisor.py", "--config", $Config)
if ($Once)    { $pyArgs += "--once" }
if ($DryRun)  { $pyArgs += "--dry-run" }

Write-Host "[HermesFX Supervisor] launching: py $pyArgs"
& py @pyArgs